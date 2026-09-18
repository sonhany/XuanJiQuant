from datetime import datetime

from quant.data.health import run_health_check


class FakeCache:
    def __init__(self, data):
        self.data = data

    def get(self, key):
        return self.data.get(key)


def bar(date=None):
    return {
        "date": date or datetime.now().strftime("%Y%m%d"),
        "open": 10,
        "high": 11,
        "low": 9,
        "close": 10.5,
        "volume": 1000,
        "amount": 10500,
    }


def test_full_market_health_returns_coverage_and_issue_counts_without_writing():
    current_date = datetime.now().strftime("%Y%m%d")
    cache = FakeCache({
        "stock:universe": ["600519", "000001", "300442"],
        "kline:600519:d": [bar(current_date)],
        "kline:000001:d": [bar(current_date)],
    })

    report = run_health_check(cache=cache, output_path=False)

    assert report["total_codes"] == 3
    assert report["summary"]["healthy"] == 2
    assert report["summary"]["issues"] == 1
    assert report["summary"]["coverage_pct"] == 66.67
    assert report["issue_counts"]["missing_kline"] == 1
    assert report["latest_date"] == current_date
