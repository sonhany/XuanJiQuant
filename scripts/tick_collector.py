"""Backend Tick collector for trading-relevant small universes."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant.data.cache import create_cache
from quant.data.order_book_store import store_order_book_snapshot
from quant.data.tick_store import latest_ticks, store_ticks, tick_microstructure
from quant.paper_execution.runtime import load_active_account_projection

cache = create_cache()

STATUS_KEY = "tick:collector:latest"
CONFIG_KEY = "tick:collector:config"

DEFAULT_CONFIG = {
    "enabled": False,
    "interval_ms": 1000,
    "max_codes": 20,
    "tick_count": 100,
    "store_order_book": True,
    "order_book_change_only": True,
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_code(code: Any) -> str:
    c = str(code or "").strip().upper()
    c = c.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
    if c.startswith(("SH", "SZ", "BJ")):
        c = c[2:]
    return c if len(c) == 6 and c.isdigit() else ""


def _append_code(out: list[str], code: Any):
    c = _normalize_code(code)
    if c and c not in out and not c.startswith("920"):
        out.append(c)


def _codes_from_records(records: Any) -> list[str]:
    out: list[str] = []
    if isinstance(records, dict):
        records = records.values()
    if not isinstance(records, list) and not isinstance(records, tuple):
        return out
    for item in records:
        if isinstance(item, dict):
            _append_code(out, item.get("code"))
        else:
            _append_code(out, item)
    return out


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    raw = cache.get(CONFIG_KEY) or {}
    if isinstance(raw, dict):
        cfg.update(raw)
    cfg["interval_ms"] = max(500, min(int(cfg.get("interval_ms") or 1000), 5000))
    cfg["max_codes"] = max(1, min(int(cfg.get("max_codes") or 20), 50))
    cfg["tick_count"] = max(20, min(int(cfg.get("tick_count") or 100), 500))
    return cfg


def save_config(update: dict) -> dict:
    cfg = load_config()
    cfg.update({k: v for k, v in (update or {}).items() if k in DEFAULT_CONFIG})
    cfg["interval_ms"] = max(500, min(int(cfg.get("interval_ms") or 1000), 5000))
    cfg["max_codes"] = max(1, min(int(cfg.get("max_codes") or 20), 50))
    cfg["tick_count"] = max(20, min(int(cfg.get("tick_count") or 100), 500))
    cache.set(CONFIG_KEY, cfg)
    return cfg


def target_codes(max_codes: int | None = None) -> list[str]:
    cfg = load_config()
    limit = max_codes or int(cfg.get("max_codes") or 20)
    out: list[str] = []

    projection = load_active_account_projection()
    for pos in projection.get("positions") or []:
        if isinstance(pos, dict) and int(pos.get("quantity") or 0) > 0:
            _append_code(out, pos.get("code"))

    for code in cache.get("watchlist:default") or []:
        _append_code(out, code)

    for order in projection.get("orders") or []:
        if isinstance(order, dict) and str(order.get("status") or "").lower() in {"pending", "partial", "submitted", "new"}:
            _append_code(out, order.get("code"))

    return out[:limit]


def _snapshot_order_book(code: str) -> dict:
    from scripts.data_runner import _snapshot_order_book as build_snapshot_order_book

    return build_snapshot_order_book(code)


def collect_once(codes: list[str] | None = None, *, tick_count: int | None = None) -> dict:
    from quant.data import tdxrs_tick_source

    cfg = load_config()
    selected = [_normalize_code(c) for c in (codes or target_codes(cfg.get("max_codes")))]
    selected = [c for c in dict.fromkeys(selected) if c]
    count = tick_count or int(cfg.get("tick_count") or 100)
    started = time.time()
    total_written = 0
    total_books = 0
    items = {}
    errors = []
    for code in selected:
        try:
            ticks = tdxrs_tick_source.fetch_ticks(code, count=count)
            written = store_ticks(cache, code, ticks)
            total_written += written
            book_result = {"stored": 0, "reason": "disabled"}
            if cfg.get("store_order_book", True):
                order_book = _snapshot_order_book(code)
                book_result = store_order_book_snapshot(
                    cache,
                    code,
                    order_book,
                    change_only=bool(cfg.get("order_book_change_only", True)),
                )
                total_books += int(book_result.get("stored") or 0)
            items[code] = {
                "fetched": len(ticks),
                "written": written,
                "latest_count": len(latest_ticks(cache, code, limit=min(count, 200))),
                "stats": tick_microstructure(cache, code, limit=min(count, 500)),
                "order_book": book_result,
            }
        except Exception as exc:
            errors.append({"code": code, "error": str(exc)[:240]})
            items[code] = {"fetched": 0, "written": 0, "error": str(exc)[:240]}
    status = {
        "running": False,
        "pid": os.getpid(),
        "last_run": _now(),
        "interval_ms": int(cfg.get("interval_ms") or 1000),
        "target_count": len(selected),
        "targets": selected,
        "tick_written": total_written,
        "order_book_written": total_books,
        "latency_ms": round((time.time() - started) * 1000, 2),
        "errors": errors[-10:],
        "items": items,
    }
    cache.set(STATUS_KEY, status)
    return status


def daemon_loop():
    cfg = save_config({"enabled": True})
    status = {
        "running": True,
        "pid": os.getpid(),
        "started_at": _now(),
        "interval_ms": int(cfg.get("interval_ms") or 1000),
    }
    cache.set(STATUS_KEY, status)
    while True:
        cfg = load_config()
        if not cfg.get("enabled", False):
            status = {**(cache.get(STATUS_KEY) or {}), "running": False, "stopped_at": _now(), "pid": os.getpid()}
            cache.set(STATUS_KEY, status)
            return
        result = collect_once(tick_count=int(cfg.get("tick_count") or 100))
        result["running"] = True
        result["pid"] = os.getpid()
        result["next_run_in_ms"] = int(cfg.get("interval_ms") or 1000)
        cache.set(STATUS_KEY, result)
        time.sleep(max(0.5, int(cfg.get("interval_ms") or 1000) / 1000.0))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval-ms", type=int)
    parser.add_argument("--max-codes", type=int)
    parser.add_argument("--tick-count", type=int)
    args = parser.parse_args()
    update = {}
    if args.interval_ms:
        update["interval_ms"] = args.interval_ms
    if args.max_codes:
        update["max_codes"] = args.max_codes
    if args.tick_count:
        update["tick_count"] = args.tick_count
    if update:
        save_config(update)
    if args.daemon:
        daemon_loop()
        return
    out = collect_once(tick_count=args.tick_count) if args.once else {"config": load_config(), "targets": target_codes()}
    print(json.dumps({"success": True, "data": out}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
