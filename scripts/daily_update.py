"""姣忔棩澧為噺鏇存柊 鈥?鑵捐涓绘簮鍒锋柊 K绾?+ akshare 鍒锋柊璐㈠姟

鏁版嵁婧愮瓥鐣?(瑙?quant/data/source_policy.py):
  - K绾? 鑵捐(涓? 鈫?baostock(鍏滃簳), 鍙媺鏈€鍚庢棩鏈熶箣鍚庣殑鏂癒绾?  - 璐㈠姟: akshare(涓? + tushare(浜ゅ弶鏍￠獙), --financial 鏃跺叏閲忓埛鏂?  - 鑲＄エ姹? akshare(涓?, 鑷姩鍚屾鏈€鏂板叏A鑲℃竻鍗?(鏂拌偂涓婂競/閫€甯?
  - 閫傚悎鏀剁洏鍚庤繍琛?(15:30 鍚?

鐢ㄦ硶:
  python scripts/daily_update.py              # 姣忔棩K绾垮閲?(榛樿锛岀害30鍒嗛挓)
  python scripts/daily_update.py --financial  # 鍚储鍔″埛鏂?(绾?灏忔椂)
  python scripts/daily_update.py --limit 100  # 娴嬭瘯鐢紝鍙洿鏂?00鍙?
瀹氭椂 (Linux crontab锛屾瘡涓氦鏄撴棩17:30杩愯):
  30 17 * * 1-5  cd ~/XuanJiQuant && bash scripts/daily_update_cron.sh
"""
import argparse
import gc
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache
from quant.data.financial_quality import analyze_financial_history
from quant.data.kline_reconciler import fetch_kline_dual
from quant.data.snapshot import DataSnapshot, normalize_source_chain, publish_snapshot
from quant.data.source_policy import SOURCE_POLICY
from quant.data.universe import filter_trade_universe_codes
from quant.data.baostock_source import fetch_klines_range as fetch_baostock_klines_range, logout

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s', handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("daily_update")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINANCIAL_PROGRESS_FILE = os.path.join(ROOT, "data", "financial_update_progress.json")


def _kline_key_count(cache) -> int:
    conn = getattr(cache, "_conn", None)
    if conn is not None:
        row = conn.execute(
            "SELECT COUNT(*) FROM kv "
            "WHERE key LIKE 'kline:%:d' AND (exp IS NULL OR exp >= ?)",
            (time.time(),),
        ).fetchone()
        return int((row or [0])[0])
    return len(cache.keys("kline:*:d"))


def _expected_kline_date() -> str:
    try:
        from scripts.data_freshness import get_expected_date
        return get_expected_date()
    except Exception:
        return datetime.now().strftime("%Y%m%d")


def _bar_date(bar: dict) -> str:
    return str((bar or {}).get("date") or (bar or {}).get("d") or "")


def _latest_bar_date(bars: list) -> str:
    if not bars:
        return ""
    return _bar_date(bars[-1])


def _fetch_count_for_gap(last_date: str, expected_date: str) -> int:
    if not last_date or not expected_date:
        return 300
    try:
        last = datetime.strptime(last_date[:8], "%Y%m%d")
        expected = datetime.strptime(expected_date[:8], "%Y%m%d")
        days = max(1, (expected - last).days)
    except Exception:
        return 60
    if days <= 3:
        return 20
    return min(300, max(30, int(days * 1.6) + 10))


def _fetch_incremental_remote(code: str, *, count: int, start: str, today: str) -> dict:
    try:
        if not start:
            checked = fetch_kline_dual(code, count=300, period="1d")
        else:
            checked = fetch_kline_dual(code, count=count, period="1d")
        fetched = checked.get("bars") if checked.get("ok") else []
        source = checked.get("primary_source") or ""
        warning = ";".join(checked.get("warnings") or [])
    except Exception as e:
        logger.debug(f"[{code}] kline dual incremental failed: {e}")
        fetched = []
        source = ""
        warning = str(e)[:160]
    if not fetched:
        try:
            fetched = fetch_baostock_klines_range(code, start, today)
            source = "baostock_range" if fetched else source
        except Exception as e:
            logger.debug(f"[{code}] baostock fallback failed: {e}")
            fetched = []
            warning = f"{warning}; baostock={str(e)[:120]}".strip("; ")
    return {"code": code, "bars": fetched or [], "source": source, "warning": warning}


def sync_universe(force: bool = False) -> List[str]:
    """Sync the tradable A-share universe, excluding unsupported 920xxx codes."""
    cache = create_cache()
    if not force:
        cached = filter_trade_universe_codes(cache.get('stock:universe') or [])
        if cached:
            logger.info(f'stock universe loaded from cache: {len(cached)}')
            return cached
    try:
        import akshare as ak
        df = ak.stock_info_a_code_name()
        codes = filter_trade_universe_codes(str(c) for c in df['code'].tolist())
        cache.set('stock:universe', codes)
        for _, row in df.iterrows():
            code = str(row['code'])
            if code not in codes:
                continue
            name = str(row['name'])
            if name and name != 'nan':
                cache.set(f'stock:name:{code}', name)
        logger.info(f'stock universe synced: {len(codes)}')
        return codes
    except Exception as e:
        logger.warning(f"鑲＄エ姹犲悓姝ュけ璐ワ紝鐢ㄧ紦瀛? {e}")
        return filter_trade_universe_codes(cache.get('stock:universe') or [])


def incremental_klines(
    codes: List[str],
    cache,
    *,
    expected_date: str = "",
    workers: int = 1,
    sleep_sec: float = 0.0,
) -> dict:
    """Incrementally update daily K-lines after each symbol latest cached date."""
    today = datetime.now().strftime('%Y-%m-%d')
    expected_date = str(expected_date or _expected_kline_date()).replace("-", "")[:8]
    ok = skip = err = total_new = 0
    remote_fetches = 0
    baostock_used = False
    t0 = time.time()
    pending = []

    for code in codes:
        code = str(code).split('.')[0]
        key = f'kline:{code}:d'
        stored = cache.get(key) or []
        existing = [
            bar
            for bar in stored
            if _bar_date(bar) and (not expected_date or _bar_date(bar) <= expected_date)
        ]
        if len(existing) != len(stored):
            cache.set(key, existing)
        last_date = _latest_bar_date(existing)

        if last_date and expected_date and last_date >= expected_date:
            skip += 1
            continue
        if last_date:
            start = f"{last_date[:4]}-{last_date[4:6]}-{last_date[6:8]}"
            fetch_count = _fetch_count_for_gap(last_date, expected_date)
        else:
            start = (datetime.now().replace(year=datetime.now().year - 1)).strftime('%Y-%m-%d')
            fetch_count = 300

        pending.append({
            "code": code,
            "key": key,
            "existing": existing,
            "start": start,
            "count": fetch_count,
        })

    total = len(codes)
    workers = max(1, int(workers or 1))

    def _handle_result(item: dict, result: dict, done: int):
        nonlocal ok, skip, err, total_new, remote_fetches, baostock_used
        code = item["code"]
        key = item["key"]
        existing = item["existing"]
        fetched = [
            bar
            for bar in (result.get("bars") or [])
            if _bar_date(bar) and (not expected_date or _bar_date(bar) <= expected_date)
        ]
        if str(result.get("source") or "").startswith("baostock"):
            baostock_used = True
        remote_fetches += 1

        if not fetched:
            err += 1
            return

        if existing:
            existing_dates = {_bar_date(b) for b in existing}
            to_add = [b for b in fetched if _bar_date(b) and _bar_date(b) not in existing_dates]
            if to_add:
                merged = existing + to_add
                merged.sort(key=lambda x: _bar_date(x))
                merged = merged[-300:]
                cache.set(key, merged)
                total_new += len(to_add)
                ok += 1
            else:
                skip += 1
        else:
            clean = [b for b in fetched if _bar_date(b)]
            if clean:
                cache.set(key, clean[-300:])
                total_new += len(clean)
                ok += 1
            else:
                err += 1

        if done % 500 == 0 or done == total:
            elapsed = time.time() - t0
            logger.info(
                f"K线增量 [{done}/{total}] ok={ok} skip={skip} err={err} "
                f"新增{total_new}根 ({done/max(elapsed, 1e-6):.1f}/s)"
            )
        if sleep_sec > 0:
            time.sleep(float(sleep_sec))

    if workers <= 1:
        done = skip
        for item in pending:
            done += 1
            result = _fetch_incremental_remote(item["code"], count=item["count"], start=item["start"], today=today)
            _handle_result(item, result, done)
    else:
        done = skip
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _fetch_incremental_remote,
                    item["code"],
                    count=item["count"],
                    start=item["start"],
                    today=today,
                ): item
                for item in pending
            }
            for fut in as_completed(futures):
                done += 1
                item = futures[fut]
                try:
                    result = fut.result()
                except Exception as e:
                    result = {"code": item["code"], "bars": [], "warning": str(e)[:160]}
                _handle_result(item, result, done)

    elapsed = time.time() - t0
    logger.info(
        f"K线增量 [{total}/{total}] ok={ok} skip={skip} err={err} "
        f"新增{total_new}根 ({total/max(elapsed, 1e-6):.1f}/s)"
    )
    if baostock_used:
        logout()
    logger.info(f'kline incremental finished: ok={ok} skip={skip} err={err}, new_bars={total_new}, remote_fetches={remote_fetches}, elapsed_min={elapsed/60:.1f}')
    return {'ok': ok, 'skip': skip, 'err': err, 'new_bars': total_new, 'remote_fetches': remote_fetches}


def _financial_universe_hash(codes: List[str]) -> str:
    payload = ",".join(str(code).split(".")[0] for code in codes)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _financial_history_is_current(records) -> bool:
    if not isinstance(records, list) or len(records) < 4:
        return False
    quality = analyze_financial_history(records)
    return (
        quality["freshness"]["status"] == "current"
        and quality["completeness"]["latest_complete"]
    )


def _load_financial_progress(progress_file: str) -> dict:
    try:
        with open(progress_file, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _save_financial_progress(progress_file: str, state: dict) -> None:
    os.makedirs(os.path.dirname(progress_file), exist_ok=True)
    temp_file = f"{progress_file}.tmp.{os.getpid()}"
    with open(temp_file, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False)
    os.replace(temp_file, progress_file)


def refresh_financials(
    codes: List[str],
    cache,
    *,
    sleep_sec: float = 0.1,
    progress_file: str = FINANCIAL_PROGRESS_FILE,
    fetcher=None,
    checkpoint_every: int = 20,
) -> dict:
    """Refresh fundamentals through the configured financial reconciler."""
    if fetcher is None:
        from quant.data.financial_reconciler import fetch_financial_crosscheck
        fetcher = fetch_financial_crosscheck

    codes = [str(code).split(".")[0] for code in codes]
    total = len(codes)
    checkpoint_every = max(1, int(checkpoint_every or 1))
    universe_hash = _financial_universe_hash(codes)
    previous = _load_financial_progress(progress_file)
    resumable = (
        previous.get("universe_hash") == universe_hash
        and previous.get("status") in {
            "running",
            "interrupted",
            "completed_with_errors",
        }
    )
    completed = [
        code
        for code in (previous.get("completed_codes") or [])
        if code in codes
    ] if resumable else []
    completed_set = set(completed)
    resumed = len(completed)
    cached_codes = []
    for code in codes:
        if code in completed_set:
            continue
        if _financial_history_is_current(cache.get(f"fin:abstract:{code}")):
            cached_codes.append(code)
            completed.append(code)
            completed_set.add(code)
    cached = len(cached_codes)
    initial_done = len(completed)
    ok = initial_done
    err = 0
    failed_codes = []
    t0 = time.time()
    started_at = (
        previous.get("started_at")
        if resumable and previous.get("started_at")
        else datetime.now().isoformat(timespec="seconds")
    )
    state = {
        "status": "running",
        "universe_hash": universe_hash,
        "total": total,
        "done": initial_done,
        "ok": ok,
        "err": 0,
        "resumed": resumed,
        "cached": cached,
        "completed_codes": completed,
        "failed_codes": [],
        "started_at": started_at,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save_financial_progress(progress_file, state)

    if initial_done:
        logger.info(
            f"财务 [{initial_done}/{total}] ok={ok} err=0 "
            f"(断点{resumed}，缓存有效{cached})"
        )

    pending = [code for code in codes if code not in completed_set]
    try:
        for i, code in enumerate(pending, 1):
            try:
                result = fetcher(code)
                if result.get("ok"):
                    cache.set(f'fin:crosscheck:{code}', result)
                    if result.get("akshare_records"):
                        cache.set(f'fin:abstract:{code}', result["akshare_records"])
                    else:
                        cache.set(f'fin:abstract:{code}', [result.get("merged") or {}])
                    if result.get("tushare_records"):
                        cache.set(f'fin:tushare:{code}', result["tushare_records"])
                    completed.append(code)
                    completed_set.add(code)
                    ok += 1
                else:
                    failed_codes.append(code)
                    err += 1
            except Exception:
                failed_codes.append(code)
                err += 1
            done = initial_done + i
            if i % checkpoint_every == 0 or done == total:
                elapsed = time.time() - t0
                state.update({
                    "done": done,
                    "ok": ok,
                    "err": err,
                    "completed_codes": completed,
                    "failed_codes": failed_codes[-100:],
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                })
                _save_financial_progress(progress_file, state)
                logger.info(
                    f"财务 [{done}/{total}] ok={ok} err={err} "
                    f"({i/max(elapsed, 1e-6):.2f}/s)"
                )
                gc.collect()
            if sleep_sec > 0:
                time.sleep(float(sleep_sec))
    except BaseException:
        state.update({
            "status": "interrupted",
            "done": min(total, resumed + len(completed) - resumed + len(failed_codes)),
            "ok": ok,
            "err": err,
            "completed_codes": completed,
            "failed_codes": failed_codes[-100:],
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        })
        _save_financial_progress(progress_file, state)
        gc.collect()
        raise

    elapsed = time.time() - t0
    state.update({
        "status": "completed" if err == 0 else "completed_with_errors",
        "done": total,
        "ok": ok,
        "err": err,
        "completed_codes": completed,
        "failed_codes": failed_codes[-100:],
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    })
    _save_financial_progress(progress_file, state)
    logger.info(f"财务 [{total}/{total}] ok={ok} err={err} ({len(pending)/max(elapsed, 1e-6):.2f}/s)")
    logger.info(f'financial refresh finished: ok={ok} err={err}, elapsed_min={elapsed/60:.1f}')
    return {
        'ok': ok,
        'err': err,
        'done': total,
        'total': total,
        'resumed': resumed,
        'cached': cached,
    }


def run_daily_update(
    *,
    financial: bool = False,
    financial_only: bool = False,
    limit: int = 0,
    workers: int = 0,
    refresh_universe: bool = False,
    selected_codes: Optional[List[str]] = None,
) -> dict:
    codes = filter_trade_universe_codes(selected_codes or [])
    if not codes:
        codes = sync_universe(force=refresh_universe)
    if limit > 0:
        codes = codes[:limit]

    cache = create_cache()
    workers = int(workers or os.getenv("XUANJI_UPDATE_WORKERS", "8") or 8)
    results = {}
    if not financial_only:
        expected_date = _expected_kline_date()
        results['kline'] = incremental_klines(
            codes,
            cache,
            expected_date=expected_date,
            workers=workers,
            sleep_sec=float(os.getenv("XUANJI_KLINE_UPDATE_SLEEP", "0") or 0),
        )
        kline_result = results['kline']
        expected_count = len(codes)
        available_count = 0
        for code in codes:
            bars = cache.get(f"kline:{str(code).split('.')[0]}:d") or []
            latest = _latest_bar_date(bars)
            if latest and latest >= expected_date:
                available_count += 1
        unavailable_count = max(0, expected_count - available_count)
        min_coverage = min(
            1.0,
            max(0.0, float(os.getenv("FULL_MARKET_KLINE_MIN_COVERAGE", "0.95") or 0.95)),
        )
        coverage = available_count / expected_count if expected_count else 0.0
        quality_status = (
            'passed'
            if expected_count > 0 and coverage >= min_coverage
            else ('partial' if available_count > 0 else 'failed')
        )
        fetch_errors = max(0, int(kline_result.get('err') or 0))
        sources = kline_result.get('sources') or [
            SOURCE_POLICY['kline_primary'],
            f"{SOURCE_POLICY['kline_cross_check']}_cross_check",
            *SOURCE_POLICY['kline_fallbacks'],
        ]
        universe_hash = hashlib.sha256(
            ",".join(codes).encode("utf-8")
        ).hexdigest()
        content_hash = hashlib.sha256(
            json.dumps(
                {
                    "as_of": expected_date,
                    "universe_hash": universe_hash,
                    "result": kline_result,
                },
                ensure_ascii=True,
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        published_at = datetime.now().astimezone().isoformat(timespec="seconds")
        snapshot = DataSnapshot(
            snapshot_id=f"a-share-daily-{expected_date}-{content_hash[:12]}",
            dataset="a_share_daily",
            as_of=(
                f"{expected_date[:4]}-{expected_date[4:6]}-{expected_date[6:8]}"
                if len(expected_date) == 8
                else expected_date
            ),
            published_at=published_at,
            universe_version=universe_hash,
            expected_count=expected_count,
            available_count=available_count,
            source_chain=normalize_source_chain(sources),
            content_hash=content_hash,
            quality_status=quality_status,
            freshness_status="fresh" if quality_status == "passed" else "unknown",
            failure_reasons=(
                ()
                if quality_status == "passed"
                else ("daily_kline_coverage_below_gate",)
            ),
            warnings=(
                (f"nonfatal_fetch_errors:{fetch_errors}",)
                if quality_status == "passed" and fetch_errors
                else ()
            ),
        )
        results['data_snapshot'] = publish_snapshot(cache, snapshot)
    if financial:
        results['financial'] = refresh_financials(
            codes,
            cache,
            sleep_sec=float(os.getenv("XUANJI_FINANCIAL_UPDATE_SLEEP", "0.1") or 0.1),
        )
    return results


def main():
    ap = argparse.ArgumentParser(description='姣忔棩澧為噺鏇存柊 (K绾?璐㈠姟)')
    ap.add_argument('--financial', action='store_true', help='鍚屾椂鍒锋柊璐㈠姟 (鎱紝绾?灏忔椂)')
    ap.add_argument('--financial-only', action='store_true', help='refresh financial data only; skip K-line update')
    ap.add_argument('--with-kline', action='store_true', help='with --financial, also run K-line incremental update')
    ap.add_argument('--limit', type=int, default=0, help='闄愬埗鏁伴噺(娴嬭瘯鐢?')
    ap.add_argument('--workers', type=int, default=0, help='K 绾垮苟鍙戞洿鏂扮嚎绋嬫暟')
    ap.add_argument('--refresh-universe', action='store_true', help='refresh A-share universe before update')
    ap.add_argument('--codes', default='', help='comma-separated stock codes for selective update')
    args = ap.parse_args()

    logger.info("=" * 55)
    logger.info(f"姣忔棩澧為噺鏇存柊 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    logger.info("=" * 55)

    financial_only = bool(args.financial_only or (args.financial and not args.with_kline))
    results = run_daily_update(
        financial=bool(args.financial or args.financial_only),
        financial_only=financial_only,
        limit=args.limit,
        workers=args.workers,
        refresh_universe=args.refresh_universe,
        selected_codes=args.codes.split(',') if args.codes else None,
    )

    # 4. Summary.
    cache = create_cache()
    kline_count = _kline_key_count(cache)
    logger.info("=" * 55)
    logger.info("鏇存柊瀹屾垚!")
    logger.info(f"  K绾胯偂绁? {kline_count}")
    if 'kline' in results:
        logger.info(f"  new kline bars: {results['kline']['new_bars']}")
    if 'financial' in results:
        logger.info(f"  璐㈠姟鍒锋柊: ok={results['financial']['ok']}")
    logger.info("=" * 55)


if __name__ == '__main__':
    main()
