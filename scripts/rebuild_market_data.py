"""Parallel market data rebuild.

Purpose:
  - Rebuild near-one-year A-share daily K-line data quickly.
  - Rebuild financial abstracts when requested.
  - Keep the source policy: TdxQuant primary, Tencent cross-check,
    Sina/Baostock fallback where needed.

Usage:
  python scripts/rebuild_market_data.py --phase kline --fresh
  python scripts/rebuild_market_data.py --phase both --fresh --workers 12
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant.data.cache import create_cache
from quant.data.daily_summary import ensure_table, upsert_from_bars
from quant.data.kline_reconciler import fetch_kline_dual
from quant.data.universe import filter_trade_universe_codes, normalize_universe_code
from quant.data.tencent_source import fetch_klines as fetch_tencent_klines, normalize_code
from quant.data.sina_source import fetch_klines as fetch_sina_klines

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROGRESS_FILE = os.path.join(ROOT, "data", "download_progress.json")


def restore_universe_from_daily_summary(cache) -> List[str]:
    """Restore stock universe and names from the indexed daily summary table."""
    if not ensure_table(cache):
        return []
    conn = getattr(cache, "_conn", None)
    lock = getattr(cache, "_lock", None)
    if conn is None:
        return []
    ctx = lock if lock is not None else None
    if ctx is None:
        rows = conn.execute("SELECT code, name FROM stock_daily_summary ORDER BY rowid").fetchall()
    else:
        with ctx:
            rows = conn.execute("SELECT code, name FROM stock_daily_summary ORDER BY rowid").fetchall()
    codes = []
    for raw_code, raw_name in rows:
        code = normalize_universe_code(raw_code)
        if not filter_trade_universe_codes([code]):
            continue
        if code in codes:
            continue
        codes.append(code)
        name = str(raw_name or "").strip()
        if name and name != code:
            cache.set(f"stock:name:{code}", name)
    cache.set("stock:universe", codes)
    return codes


def restore_universe_from_factor_snapshot(cache) -> List[str]:
    path = os.path.join(ROOT, "data", "factor_snapshot_latest.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            rows = (json.load(f) or {}).get("rows") or []
    except Exception:
        rows = []
    codes = []
    for row in rows:
        code = normalize_universe_code(row.get("code"))
        if not filter_trade_universe_codes([code]) or code in codes:
            continue
        codes.append(code)
        name = str(row.get("name") or "").strip()
        if name and name != code:
            cache.set(f"stock:name:{code}", name)
    if codes:
        cache.set("stock:universe", codes)
    return codes


def cleanup_invalid_market_data(cache, valid_codes: List[str] | None = None) -> dict:
    """Delete unsupported, empty, or out-of-universe market-data KV records."""
    valid = set(filter_trade_universe_codes(valid_codes or []))
    removed = []

    def should_remove_code(code: str) -> bool:
        norm = normalize_universe_code(code)
        if not filter_trade_universe_codes([norm]):
            return True
        return bool(valid) and norm not in valid

    for key in list(cache.keys("kline:*:d")):
        parts = str(key).split(":")
        code = parts[1] if len(parts) >= 3 else ""
        raw = cache.get(key)
        if should_remove_code(code) or not isinstance(raw, list) or not raw:
            cache.delete(key)
            removed.append(key)

    for key in list(cache.keys("stock:name:*")):
        code = str(key).split(":")[-1]
        if not (len(code) == 6 and code.isdigit()) or should_remove_code(code):
            cache.delete(key)
            removed.append(key)

    for pattern in ("fin:abstract:*", "fin:crosscheck:*", "fin:tdx:*", "fin:tushare:*"):
        for key in list(cache.keys(pattern)):
            code = str(key).split(":")[-1]
            if should_remove_code(code):
                cache.delete(key)
                removed.append(key)

    existing_universe = cache.get("stock:universe") or []
    cleaned_universe = filter_trade_universe_codes(existing_universe)
    if valid:
        cleaned_universe = [c for c in cleaned_universe if c in valid]
    cache.set("stock:universe", cleaned_universe)
    return {"removed_keys": len(removed), "removed_sample": removed[:20], "universe_size": len(cleaned_universe)}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _emit(event: dict) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


def _load_universe(cache) -> List[str]:
    try:
        import akshare as ak
        df = ak.stock_info_a_code_name()
        codes = []
        for _, row in df.iterrows():
            code = normalize_code(str(row.get("code") or ""))
            if len(code) == 6 and code.isdigit() and code not in codes:
                codes.append(code)
                name = str(row.get("name") or "")
                if name and name != "nan":
                    cache.set(f"stock:name:{code}", name)
        codes = filter_trade_universe_codes(codes)
        cache.set("stock:universe", codes)
        return codes
    except Exception:
        codes = [normalize_code(str(c)) for c in (cache.get("stock:universe") or [])]
        codes = filter_trade_universe_codes(codes)
        if codes:
            return codes
        codes = restore_universe_from_daily_summary(cache)
        if codes:
            return codes
        return restore_universe_from_factor_snapshot(cache)


def _save_progress(payload: dict) -> None:
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def _compact_state(payload: dict) -> dict:
    compact = {k: v for k, v in payload.items() if k not in ("universe", "kline_done", "financial_done")}
    compact["universe_count"] = len(payload.get("universe") or [])
    compact["kline_done_count"] = len(payload.get("kline_done") or [])
    compact["financial_done_count"] = len(payload.get("financial_done") or [])
    if payload.get("failed_sample"):
        compact["failed_sample"] = list(payload.get("failed_sample") or [])[-20:]
    return compact


def _record(cache, payload: dict) -> None:
    payload = {**payload, "updated_at": _now()}
    cache.set("data:rebuild:latest", _compact_state(payload))
    _save_progress(_compact_state(payload))


def _fetch_kline_fast(code: str, count: int) -> dict:
    try:
        checked = fetch_kline_dual(code, count=count, period="1d")
        if checked.get("ok") and checked.get("bars"):
            cross = checked.get("cross_check_status")
            source = "tdx_quant+tencent_check" if cross == "matched" else "tdx_quant"
            return {
                "code": code,
                "ok": True,
                "source": source,
                "bars": checked["bars"],
                "cross_check_status": cross,
                "warnings": checked.get("warnings") or [],
            }
        tdx_error = checked.get("primary_error") or ";".join(checked.get("warnings") or []) or "empty"
    except Exception as e:
        tdx_error = str(e)[:160]
    if "price jump detected" in str(tdx_error):
        try:
            from quant.data.tdx_quant_source import fetch_klines_allow_price_jumps

            bars = fetch_klines_allow_price_jumps(code, count=count, period="1d")
            if bars:
                return {
                    "code": code,
                    "ok": True,
                    "source": "tdx_quant_jump_review",
                    "bars": bars,
                    "warnings": [f"tdx strict series validation bypassed: {tdx_error}"],
                }
        except Exception:
            pass
    try:
        bars = fetch_tencent_klines(code, count=count)
        if bars:
            return {"code": code, "ok": True, "source": "tencent", "bars": bars, "warnings": [f"tdx={tdx_error}"]}
    except Exception as e:
        tencent_error = str(e)[:160]
    else:
        tencent_error = "empty"
    try:
        bars = fetch_sina_klines(code, count=count)
        if bars:
            return {"code": code, "ok": True, "source": "sina", "bars": bars}
    except Exception as e:
        return {"code": code, "ok": False, "source": "", "error": f"tdx={tdx_error}; tencent={tencent_error}; sina={str(e)[:160]}"}
    return {"code": code, "ok": False, "source": "", "error": f"tdx={tdx_error}; tencent={tencent_error}; sina=empty"}


def rebuild_klines(codes: List[str], cache, count: int, workers: int, started_at: str) -> dict:
    done, failed, source_counts = [], [], {
        "tdx_quant+tencent_check": 0,
        "tdx_quant": 0,
        "tencent": 0,
        "sina": 0,
        "baostock": 0,
        "tdx_quant_jump_review": 0,
    }
    total = len(codes)
    t0 = time.time()
    state = {
        "phase": "kline",
        "started_at": started_at,
        "universe": codes,
        "kline_done": done,
        "financial_done": [],
        "total": total,
        "done": 0,
        "ok": 0,
        "err": 0,
        "source_counts": source_counts,
        "running": True,
    }
    _record(cache, state)
    _emit({"phase": "kline", "event": "start", "total": total, "workers": workers})

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(_fetch_kline_fast, code, count): code for code in codes}
        for idx, fut in enumerate(as_completed(futures), 1):
            code = futures[fut]
            try:
                result = fut.result()
            except Exception as e:
                result = {"code": code, "ok": False, "error": str(e)[:160]}
            if result.get("ok"):
                cache.set(f"kline:{code}:d", result["bars"])
                upsert_from_bars(cache, code, result["bars"])
                done.append(code)
                source = result.get("source") or "unknown"
                source_counts[source] = source_counts.get(source, 0) + 1
            else:
                failed.append({"code": code, "error": result.get("error", "")})

            if idx % 25 == 0 or idx == total:
                state.update({
                    "done": idx,
                    "ok": len(done),
                    "err": len(failed),
                    "kline_done": done,
                    "failed_sample": failed[-20:],
                    "elapsed_sec": round(time.time() - t0, 1),
                    "source_counts": source_counts,
                })
                _record(cache, state)
                _emit({k: state[k] for k in ("phase", "done", "total", "ok", "err", "elapsed_sec", "source_counts")})

    state.update({
        "done": total,
        "ok": len(done),
        "err": len(failed),
        "kline_done": done,
        "failed_sample": failed[-50:],
        "elapsed_sec": round(time.time() - t0, 1),
        "source_counts": source_counts,
        "running": False,
        "finished_at": _now(),
    })
    _record(cache, state)
    _emit({"phase": "kline", "event": "finish", "ok": len(done), "err": len(failed), "source_counts": source_counts})
    return state


def _fetch_financial_fast(code: str) -> dict:
    from quant.data.financial_reconciler import fetch_financial_crosscheck

    try:
        result = fetch_financial_crosscheck(code)
        result["code"] = code
        return result
    except Exception as e:
        return {"ok": False, "code": code, "error": str(e)[:160]}


def _store_financial_result(cache, code: str, result: dict) -> None:
    cache.set(f"fin:crosscheck:{code}", result)
    if result.get("akshare_records"):
        cache.set(f"fin:abstract:{code}", result["akshare_records"])
    else:
        cache.set(f"fin:abstract:{code}", [result.get("merged") or {"code": code, "source": "empty"}])
    if result.get("tdx_raw"):
        cache.set(f"fin:tdx:{code}", result["tdx_raw"])
    if result.get("tushare_records"):
        cache.set(f"fin:tushare:{code}", result["tushare_records"])


def _default_financial_period() -> str:
    today = datetime.now()
    year = today.year
    month = today.month
    if month >= 11:
        return f"{year}0930"
    if month >= 8:
        return f"{year}0630"
    if month >= 5:
        return f"{year}0331"
    return f"{year - 1}1231"


def _records_by_code(df: Any) -> Dict[str, dict]:
    if df is None or getattr(df, "empty", True):
        return {}
    out: Dict[str, dict] = {}
    for _, row in df.iterrows():
        raw = row.to_dict()
        values = list(raw.values())
        code = normalize_code(str(raw.get("股票代码") or raw.get("代码") or (values[1] if len(values) > 1 else "")))
        if not code:
            continue
        cleaned = {}
        for key, value in raw.items():
            if value == value:
                cleaned[str(key)] = value
        out[code] = cleaned
    return out


def rebuild_financials_bulk(codes: List[str], cache, started_at: str, period: str) -> dict:
    valid = set(filter_trade_universe_codes(codes))
    state = {
        "phase": "financial",
        "mode": "akshare_em_bulk",
        "period": period,
        "started_at": started_at,
        "universe": codes,
        "financial_done": [],
        "total": len(codes),
        "done": 0,
        "ok": 0,
        "err": 0,
        "running": True,
    }
    _record(cache, state)
    _emit({"phase": "financial", "event": "bulk_start", "period": period, "total": len(codes)})
    t0 = time.time()
    try:
        import akshare as ak

        tables = {
            "performance": _records_by_code(ak.stock_yjbb_em(date=period)),
            "income": _records_by_code(ak.stock_lrb_em(date=period)),
            "balance": _records_by_code(ak.stock_zcfz_em(date=period)),
            "cashflow": _records_by_code(ak.stock_xjll_em(date=period)),
        }
    except Exception as e:
        state.update({
            "running": False,
            "finished_at": _now(),
            "failed_sample": [{"code": "*", "error": str(e)[:240]}],
            "elapsed_sec": round(time.time() - t0, 1),
        })
        _record(cache, state)
        _emit({"phase": "financial", "event": "bulk_failed", "error": str(e)[:240]})
        return state

    all_codes = set()
    for rows in tables.values():
        all_codes.update(rows.keys())
    target_codes = [code for code in codes if code in all_codes and code in valid]
    done, failed = [], []
    for idx, code in enumerate(target_codes, 1):
        merged = {
            "code": code,
            "name": cache.get(f"stock:name:{code}") or code,
            "period": period,
            "source": "akshare_em_bulk",
            "tables": {name: rows.get(code) for name, rows in tables.items() if rows.get(code)},
        }
        performance = merged["tables"].get("performance") or {}
        values = list(performance.values())
        if len(values) > 2 and values[2]:
            merged["name"] = str(values[2])
            cache.set(f"stock:name:{code}", merged["name"])
        result = {
            "ok": True,
            "code": code,
            "primary_source": "akshare_em_bulk",
            "cross_check_sources": [],
            "sources": {name: {"available": bool(rows.get(code)), "records": 1 if rows.get(code) else 0} for name, rows in tables.items()},
            "merged": merged,
            "akshare_records": [merged],
            "warnings": [],
        }
        _store_financial_result(cache, code, result)
        done.append(code)
        if idx % 200 == 0 or idx == len(target_codes):
            state.update({
                "done": idx,
                "ok": len(done),
                "err": len(failed),
                "financial_done": done,
                "failed_sample": failed[-20:],
                "elapsed_sec": round(time.time() - t0, 1),
            })
            _record(cache, state)
            _emit({k: state[k] for k in ("phase", "done", "total", "ok", "err", "elapsed_sec")})
    missing = [code for code in codes if code not in set(done)]
    failed = [{"code": code, "error": "not_in_bulk_financial_tables"} for code in missing[:50]]
    state.update({
        "done": len(target_codes),
        "ok": len(done),
        "err": len(missing),
        "financial_done": done,
        "failed_sample": failed,
        "elapsed_sec": round(time.time() - t0, 1),
        "running": False,
        "finished_at": _now(),
    })
    _record(cache, state)
    _emit({"phase": "financial", "event": "bulk_finish", "ok": len(done), "err": len(missing), "period": period})
    return state


def rebuild_financials(codes: List[str], cache, started_at: str, workers: int = 4, period: str = "") -> dict:
    bulk = rebuild_financials_bulk(codes, cache, started_at, period or _default_financial_period())
    if bulk.get("ok", 0) > 0:
        return bulk
    done, failed = [], []
    total = len(codes)
    state = {
        "phase": "financial",
        "started_at": started_at,
        "universe": codes,
        "kline_done": [],
        "financial_done": done,
        "total": total,
        "done": 0,
        "ok": 0,
        "err": 0,
        "running": True,
    }
    _record(cache, state)
    _emit({"phase": "financial", "event": "start", "total": total, "workers": workers})
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(_fetch_financial_fast, code): code for code in codes}
        for idx, fut in enumerate(as_completed(futures), 1):
            code = futures[fut]
            try:
                result = fut.result()
            except Exception as e:
                result = {"ok": False, "code": code, "error": str(e)[:160]}
            if result.get("ok"):
                _store_financial_result(cache, code, result)
                done.append(code)
            else:
                failed.append({"code": code, "error": result.get("error") or "empty"})
            if idx % 20 == 0 or idx == total:
                state.update({
                    "done": idx,
                    "ok": len(done),
                    "err": len(failed),
                    "financial_done": done,
                    "failed_sample": failed[-20:],
                    "elapsed_sec": round(time.time() - t0, 1),
                })
                _record(cache, state)
                _emit({k: state[k] for k in ("phase", "done", "total", "ok", "err", "elapsed_sec")})
    state.update({
        "done": total,
        "ok": len(done),
        "err": len(failed),
        "financial_done": done,
        "failed_sample": failed[-50:],
        "elapsed_sec": round(time.time() - t0, 1),
        "running": False,
        "finished_at": _now(),
    })
    _record(cache, state)
    _emit({"phase": "financial", "event": "finish", "ok": len(done), "err": len(failed)})
    return state


def main() -> int:
    ap = argparse.ArgumentParser(description="Parallel market data rebuild")
    ap.add_argument("--phase", choices=["kline", "financial", "both"], default="both")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--count", type=int, default=300)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--financial-period", default="", help="report period like 20260331; default picks the latest likely period")
    ap.add_argument("--fresh", action="store_true", help="re-fetch even when data already exists")
    args = ap.parse_args()

    cache = create_cache()
    codes = _load_universe(cache)
    if args.limit > 0:
        codes = codes[:args.limit]
    started_at = _now()
    _emit({"event": "universe", "count": len(codes), "started_at": started_at})
    cleanup = cleanup_invalid_market_data(cache, codes)
    _emit({"event": "cleanup", **cleanup})

    if args.phase in ("kline", "both"):
        target = codes if args.fresh else [c for c in codes if not cache.get(f"kline:{c}:d")]
        rebuild_klines(target, cache, args.count, args.workers, started_at)
    if args.phase in ("financial", "both"):
        target = codes if args.fresh else [c for c in codes if not cache.get(f"fin:abstract:{c}")]
        rebuild_financials(target, cache, started_at, args.workers, args.financial_period)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
