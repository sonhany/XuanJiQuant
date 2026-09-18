from datetime import datetime

from scripts import paper_runner


class EmptyCache:
    def get(self, key):
        return None


def test_paper_config_supplies_defaults_when_cache_is_empty():
    config = paper_runner._paper_config(EmptyCache())

    assert config["strategy_name"] == "ma_cross"
    assert config["trade_time"] == "15:05"
    assert config["risk"]["kill_switch"] is False


def test_refresh_next_run_recomputes_stale_status_value():
    status = {
        "running": True,
        "last_run": "2026-07-10 09:52:41",
        "last_run_date": "2026-07-10",
        "next_run": "2026-07-10 15:05",
    }

    refreshed = paper_runner._refresh_next_run(
        status,
        {"trade_time": "15:05"},
        now=datetime(2026, 7, 12, 10, 0, 0),
    )

    assert refreshed["next_run"].startswith("2026-07-13 15:05")


def test_refresh_next_run_keeps_future_status_value():
    status = {
        "running": True,
        "next_run": "2026-07-13 15:05",
    }

    refreshed = paper_runner._refresh_next_run(
        status,
        {"trade_time": "15:05"},
        now=datetime(2026, 7, 12, 10, 0, 0),
    )

    assert refreshed["next_run"] == "2026-07-13 15:05"
