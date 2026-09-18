import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from quant.data.control_plane import _pid_alive
from quant.data.sync_status import (
    build_daemon_status,
    heartbeat_fresh,
    normalize_watch_codes,
)


def test_normalize_watch_codes_deduplicates_and_filters_unsupported_codes():
    assert normalize_watch_codes(
        ["600519.SH", "sz000001", "600519", "920001", "bad", "", "300442"]
    ) == ["600519", "000001", "300442"]


def test_build_daemon_status_contains_replayable_operational_fields():
    status = build_daemon_status(
        running=True,
        pid=1234,
        codes=["600519", "000001"],
        session={"session": "market", "is_trading": True, "is_afterhours": False},
        quotes={
            "sh600519": {"source": "tdx_quant"},
            "sz000001": {"source": "sina"},
        },
        cycle=7,
        last_error="",
        now=datetime(2026, 7, 13, 10, 30, 0),
    )

    assert status["running"] is True
    assert status["pid"] == 1234
    assert status["watch_count"] == 2
    assert status["quote_count"] == 2
    assert status["cycle"] == 7
    assert status["session"] == "market"
    assert status["source_counts"] == {"tdx_quant": 1, "sina": 1}
    assert status["heartbeat_at"] == "2026-07-13T10:30:00"


def test_heartbeat_fresh_requires_running_recent_heartbeat_and_live_pid():
    now = datetime(2026, 7, 13, 10, 30, 0)
    recent = {
        "running": True,
        "pid": 1234,
        "heartbeat_at": (now - timedelta(seconds=15)).isoformat(timespec="seconds"),
    }
    stale = {
        **recent,
        "heartbeat_at": (now - timedelta(minutes=5)).isoformat(timespec="seconds"),
    }

    assert heartbeat_fresh(recent, now=now, pid_alive=lambda pid: pid == 1234)
    assert not heartbeat_fresh(stale, now=now, pid_alive=lambda _pid: True)
    assert not heartbeat_fresh(recent, now=now, pid_alive=lambda _pid: False)


def test_control_plane_detects_current_process_as_alive():
    assert _pid_alive(os.getpid()) is True


def test_importing_sync_service_does_not_configure_stdout_logging():
    script = """
import logging
import sys

import quant.data.sync_service

stdout_handlers = [
    type(handler).__name__
    for handler in logging.getLogger().handlers
    if getattr(handler, "stream", None) is sys.stdout
]
if stdout_handlers:
    raise SystemExit(f"stdout logging handlers installed: {stdout_handlers}")
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_sync_service_has_no_reverse_dependency_on_agent():
    import quant.data.sync_service as sync_service

    source = Path(sync_service.__file__).read_text(encoding="utf-8")
    assert "quant.agent" not in source
    assert "sync_agent_realtime" not in source


def test_default_sync_watch_set_prioritizes_current_positions_before_universe_cap(
    monkeypatch,
):
    import quant.data.sync_service as sync_service
    from quant.data.cache import MemoryCache

    cache = MemoryCache()
    cache.set("stock:universe", [f"{code:06d}" for code in range(1, 251)])
    monkeypatch.setattr(
        sync_service,
        "load_active_account_projection",
        lambda: {
            "ledger_authority": "f5",
            "positions": [
                {"code": "600016", "quantity": 28_500},
                {"code": "600817", "quantity": 22_100},
            ],
        },
    )
    monkeypatch.setattr(sync_service, "create_cache", lambda: cache)

    codes = sync_service.SyncService()._load_watch_codes()

    assert codes[:2] == ["600016", "600817"]
    assert len(codes) == 200
    assert "600016" in codes
    assert "600817" in codes


def _bar(date, close):
    return {
        "date": date,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 100,
        "amount": close * 100,
    }


def test_closed_merge_accepts_reviewed_price_jumps_only_for_delisting_stock(monkeypatch):
    import quant.data.sync_service as sync_service
    from quant.data.cache import MemoryCache

    cache = MemoryCache()
    cache.set("kline:000004:d", [_bar("20260622", 2.76), _bar("20260623", 0.31)])
    monkeypatch.setattr(sync_service, "create_cache", lambda: cache)
    service = sync_service.SyncService(["000004"])

    merged = service.merge_closed_bars(
        {
            "sz000004": {
                "name": "国华退",
                "open": 0.51,
                "high": 0.51,
                "low": 0.51,
                "price": 0.51,
                "volume": 100,
                "amount": 51,
            }
        }
    )

    assert merged == 1


def test_closed_merge_keeps_large_jump_quarantined_for_normal_stock(monkeypatch):
    import quant.data.sync_service as sync_service
    from quant.data.cache import MemoryCache

    cache = MemoryCache()
    cache.set("kline:000004:d", [_bar("20260622", 2.76), _bar("20260623", 0.31)])
    monkeypatch.setattr(sync_service, "create_cache", lambda: cache)
    service = sync_service.SyncService(["000004"])

    merged = service.merge_closed_bars(
        {
            "sz000004": {
                "name": "普通股票",
                "open": 0.51,
                "high": 0.51,
                "low": 0.51,
                "price": 0.51,
                "volume": 100,
                "amount": 51,
            }
        }
    )

    assert merged == 0
