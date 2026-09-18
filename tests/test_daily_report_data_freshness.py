from datetime import datetime

from scripts import daily_report


class FakeCache:
    def get(self, key):
        return None


def test_cached_report_projects_current_full_market_data_freshness(monkeypatch):
    cached = {
        "generated_at": "2026-08-05 17:00:00",
        "data": {
            "latest_kline_date": "20260805",
            "is_stale": True,
            "stale_days": 1,
        },
    }
    coverage = {
        "fresh": True,
        "expected_date": "20260806",
        "coverage_date": "20260806",
        "dominant_count": 5201,
        "expected_count": 5201,
        "total_count": 5205,
        "expected_coverage": 0.999232,
        "minimum_coverage": 0.95,
        "date_counts": {"20260806": 5201, "20260805": 4},
    }
    monkeypatch.setattr(
        "scripts.data_freshness.assess_market_kline_coverage",
        lambda **kwargs: coverage,
    )

    projected = daily_report.project_report_data_freshness(
        cached,
        FakeCache(),
        now=datetime(2026, 8, 6, 20, 0),
    )

    assert cached["data"]["latest_kline_date"] == "20260805"
    assert projected["data"]["latest_kline_date"] == "20260806"
    assert projected["data"]["expected_latest"] == "20260806"
    assert projected["data"]["is_stale"] is False
    assert projected["data"]["stale_days"] == 0
    assert projected["data"]["market_coverage"]["expected_count"] == 5201


def test_cached_report_fails_closed_when_full_market_coverage_is_incomplete(monkeypatch):
    coverage = {
        "fresh": False,
        "expected_date": "20260806",
        "coverage_date": "20260805",
        "dominant_count": 5000,
        "expected_count": 201,
        "total_count": 5205,
        "expected_coverage": 0.038617,
        "minimum_coverage": 0.95,
        "date_counts": {"20260805": 5000, "20260806": 201},
    }
    monkeypatch.setattr(
        "scripts.data_freshness.assess_market_kline_coverage",
        lambda **kwargs: coverage,
    )

    projected = daily_report.project_report_data_freshness(
        {"data": {"latest_kline_date": "20260806", "is_stale": False}},
        FakeCache(),
        now=datetime(2026, 8, 6, 20, 0),
    )

    assert projected["data"]["latest_kline_date"] == "20260805"
    assert projected["data"]["expected_latest"] == "20260806"
    assert projected["data"]["is_stale"] is True
    assert projected["data"]["stale_days"] == 1
    assert projected["data"]["market_coverage"]["expected_coverage"] == 0.038617
