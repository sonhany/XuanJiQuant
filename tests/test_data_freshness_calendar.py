from datetime import datetime

import pytest

from scripts.data_freshness import get_expected_date, is_data_stale


def test_weekend_morning_does_not_roll_back_twice():
    assert get_expected_date(datetime(2026, 7, 12, 9, 0, 0)) == "20260710"


def test_weekday_before_close_uses_previous_weekday():
    assert get_expected_date(datetime(2026, 7, 13, 9, 0, 0)) == "20260710"


def test_weekday_after_close_uses_current_day():
    assert get_expected_date(datetime(2026, 7, 10, 16, 0, 0)) == "20260710"


def test_daily_bar_settlement_buffer_keeps_previous_day_immediately_after_close():
    assert get_expected_date(datetime(2026, 8, 6, 15, 1, 0)) == "20260805"


def test_daily_bar_settlement_buffer_switches_after_configured_ready_time(monkeypatch):
    monkeypatch.setenv("DAILY_BAR_READY_TIME", "15:30")
    assert get_expected_date(datetime(2026, 8, 6, 15, 29, 59)) == "20260805"
    assert get_expected_date(datetime(2026, 8, 6, 15, 30, 0)) == "20260806"


class _Cache:
    def __init__(self, values):
        self.values = values

    def get(self, key):
        return self.values.get(key)

    def keys(self, pattern=""):
        import fnmatch

        return [key for key in self.values if fnmatch.fnmatch(key, pattern or "*")]


def test_data_freshness_can_assess_the_callers_cache_at_a_fixed_time():
    now = datetime(2026, 8, 6, 13, 21, 0)
    cache = _Cache({
        "paper:config": {"universe": ["600519"]},
        "kline:600519:d": [{"date": "20260805"}],
    })

    assert is_data_stale(cache=cache, now=now) is False


def test_full_market_coverage_uses_dominant_date_not_single_latest_symbol():
    from scripts.data_freshness import assess_market_kline_coverage

    cache = _Cache({
        "kline:000001:d": [{"date": "20260805"}],
        "kline:000002:d": [{"date": "20260805"}],
        "kline:600000:d": [{"date": "20260805"}],
        "kline:600519:d": [{"date": "20260806"}],
    })

    assessed = assess_market_kline_coverage(
        cache=cache,
        expected_date="20260806",
        minimum_coverage=0.9,
    )

    assert assessed["coverage_date"] == "20260805"
    assert assessed["expected_count"] == 1
    assert assessed["total_count"] == 4
    assert assessed["expected_coverage"] == 0.25
    assert assessed["fresh"] is False


def test_sqlite_coverage_reads_only_serialized_bar_tails():
    from scripts.data_freshness import assess_market_kline_coverage

    class _TailConnection:
        def execute(self, sql, params):
            assert "substr(value" in sql
            class _Cursor:
                @staticmethod
                def fetchall():
                    return [
                        ('...{"date":"20260820","close":10.0}]',),
                        ('...{"date":"20260820","close":11.0}]',),
                        ('...{"date":"20260819","close":12.0}]',),
                    ]

            return _Cursor()

    class _SqlTailCache:
        _conn = _TailConnection()

        def keys(self, pattern=""):
            raise AssertionError("full-value fallback must not run")

    assessed = assess_market_kline_coverage(
        cache=_SqlTailCache(),
        expected_date="20260820",
        minimum_coverage=0.5,
    )

    assert assessed["coverage_date"] == "20260820"
    assert assessed["dominant_count"] == 2
    assert assessed["expected_coverage"] == pytest.approx(2 / 3, abs=1e-6)
    assert assessed["fresh"] is True
