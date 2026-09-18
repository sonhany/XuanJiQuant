import fnmatch
import math

from scripts import data_runner


class FakeCache:
    def __init__(self, values):
        self.values = values

    def get(self, key):
        return self.values.get(key)

    def keys(self, pattern):
        return [key for key in self.values if fnmatch.fnmatch(key, pattern)]


def test_financials_returns_every_database_financial_key(monkeypatch):
    cache = FakeCache(
        {
            "stock:name:600519": "贵州茅台",
            "fin:abstract:600519": [
                {
                    "report_date": "20240331",
                    "revenue": 100.0,
                    "net_margin": math.nan,
                },
                {
                    "report_date": "20241231",
                    "revenue": 500.0,
                    "net_margin": 0.52,
                },
            ],
            "fin:crosscheck:600519": {
                "merged": {
                    "period": "20241231",
                    "tables": {
                        "income": {"营业收入": 500.0},
                        "balance": {"总资产": 900.0},
                    },
                }
            },
            "fin:future_source:600519": {
                "records": [{"period": "20240930", "metric": 7}]
            },
            "fin:abstract:000001": [{"report_date": "20241231"}],
        }
    )
    monkeypatch.setattr(data_runner, "cache", cache)

    result = data_runner.action_financials({"code": "sh600519"})

    assert result["success"] is True
    payload = result["data"]
    assert payload["code"] == "600519"
    assert payload["name"] == "贵州茅台"
    assert payload["keys"] == [
        "fin:abstract:600519",
        "fin:crosscheck:600519",
        "fin:future_source:600519",
    ]
    assert set(payload["datasets"]) == set(payload["keys"])
    assert payload["history_count"] == 2
    assert payload["latest_report_date"] == "20241231"
    assert payload["history"][0]["net_margin"] is None
    assert payload["datasets"]["fin:future_source:600519"]["records"][0]["metric"] == 7


def test_financials_rejects_invalid_code(monkeypatch):
    monkeypatch.setattr(data_runner, "cache", FakeCache({}))

    result = data_runner.action_financials({"code": "not-a-stock"})

    assert result["success"] is False
    assert result["status"] == 400


def test_financials_returns_explicit_empty_state(monkeypatch):
    monkeypatch.setattr(
        data_runner,
        "cache",
        FakeCache({"stock:name:300442": "润泽科技"}),
    )

    result = data_runner.action_financials({"code": "300442"})

    assert result["success"] is True
    assert result["data"]["keys"] == []
    assert result["data"]["datasets"] == {}
    assert result["data"]["history"] == []
    assert result["data"]["history_count"] == 0
    assert result["data"]["latest_report_date"] == ""
    assert result["data"]["quality"]["completeness"]["status"] == "missing"
    assert result["data"]["quality"]["freshness"]["status"] == "unknown"


def test_financials_returns_completeness_and_freshness_status(monkeypatch):
    monkeypatch.setattr(
        data_runner,
        "cache",
        FakeCache(
            {
                "stock:name:300450": "先导智能",
                "fin:abstract:300450": [
                    {
                        "report_date": "20251231",
                        "revenue": 10,
                        "net_profit": 2,
                        "operating_cash_flow": 3,
                    },
                    {
                        "report_date": "20260630",
                        "revenue": 4,
                        "net_profit": None,
                        "operating_cash_flow": 1,
                    },
                ],
            }
        ),
    )

    result = data_runner.action_financials({"code": "300450"})

    quality = result["data"]["quality"]
    assert quality["completeness"]["status"] == "partial"
    assert quality["completeness"]["complete_periods"] == 1
    assert quality["completeness"]["total_periods"] == 2
    assert quality["completeness"]["ratio"] == 0.5
    assert quality["completeness"]["latest_complete"] is False
    assert quality["completeness"]["latest_missing_fields"] == ["net_profit"]
    assert quality["freshness"]["status"] == "current"
    assert quality["freshness"]["latest_period"] == "20260630"
    assert quality["freshness"]["expected_period"] == "20260630"
    assert quality["coverage"] == {
        "start_period": "20251231",
        "end_period": "20260630",
    }
