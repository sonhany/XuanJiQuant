import fnmatch

from scripts import repair_financial_abstracts


class FakeCache:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ttl=None):
        self.values[key] = value

    def keys(self, pattern):
        return [
            key for key in self.values
            if fnmatch.fnmatch(key, pattern)
        ]


def test_audit_finds_missing_profit_and_cashflow_fields():
    cache = FakeCache(
        {
            "fin:abstract:000001": [
                {
                    "report_date": "20260331",
                    "revenue": 10,
                    "net_profit": 2,
                    "operating_cash_flow": 3,
                }
            ],
            "fin:abstract:300450": [
                {"report_date": "20260331", "roe": 10.2, "net_margin": 8.1}
            ],
            "fin:abstract:600000": [
                {
                    "report_date": "20260331",
                    "revenue": 20,
                    "net_profit": 4,
                }
            ],
        }
    )

    result = repair_financial_abstracts.audit_financial_abstracts(cache)

    assert result["total"] == 3
    assert result["complete"] == 1
    assert result["missing"] == 2
    assert result["missing_codes"] == ["300450", "600000"]
    assert result["missing_by_field"] == {
        "revenue": 1,
        "net_profit": 1,
        "operating_cash_flow": 2,
    }


def test_audit_requires_latest_report_to_have_all_required_fields():
    cache = FakeCache(
        {
            "fin:abstract:000563": [
                {
                    "report_date": "20260331",
                    "revenue": None,
                    "net_profit": 2,
                    "operating_cash_flow": 3,
                },
                {
                    "report_date": "20251231",
                    "revenue": 10,
                    "net_profit": 2,
                    "operating_cash_flow": 3,
                },
            ]
        }
    )

    result = repair_financial_abstracts.audit_financial_abstracts(cache)

    assert result["complete"] == 0
    assert result["missing_codes"] == ["000563"]
    assert result["details"]["000563"] == ["revenue"]


def test_merge_financial_records_preserves_old_fields_and_adds_new_amounts():
    existing = [
        {"report_date": "20260331", "roe": 10.2, "custom_metric": 7},
        {"report_date": "20251231", "roe": 9.4},
    ]
    fresh = [
        {
            "report_date": "20260331",
            "revenue": 100,
            "net_profit": 20,
            "operating_cash_flow": 30,
            "roe": None,
        },
        {
            "report_date": "20250930",
            "revenue": 80,
            "net_profit": 15,
            "operating_cash_flow": 18,
        },
    ]

    merged = repair_financial_abstracts.merge_financial_records(existing, fresh)

    latest = next(row for row in merged if row["report_date"] == "20260331")
    assert latest["roe"] == 10.2
    assert latest["custom_metric"] == 7
    assert latest["revenue"] == 100
    assert latest["net_profit"] == 20
    assert latest["operating_cash_flow"] == 30
    assert {row["report_date"] for row in merged} == {
        "20260331",
        "20251231",
        "20250930",
    }


def test_repair_writes_complete_fetch_and_preserves_failed_or_partial_records():
    original_missing = [{"report_date": "20260331", "roe": 10.2}]
    original_failed = [{"report_date": "20260331", "roe": 8.1}]
    original_partial = [{"report_date": "20260331", "roe": 6.4}]
    cache = FakeCache(
        {
            "fin:abstract:300450": original_missing,
            "fin:abstract:600001": original_failed,
            "fin:abstract:600002": original_partial,
        }
    )

    def fetcher(code):
        if code == "600001":
            raise RuntimeError("temporary source failure")
        if code == "600002":
            return [
                {
                    "report_date": "20260331",
                    "revenue": 10,
                    "net_profit": 1,
                }
            ]
        return [
            {
                "report_date": "20260331",
                "revenue": 3_690_650_989.26,
                "net_profit": 405_394_870.88,
                "operating_cash_flow": 1_247_581_972.19,
            }
        ]

    result = repair_financial_abstracts.repair_financial_abstracts(
        ["300450", "600001", "600002"],
        cache,
        fetcher=fetcher,
        workers=2,
    )

    assert result["repaired"] == 1
    assert result["failed"] == 2
    repaired = cache.get("fin:abstract:300450")[0]
    assert repaired["revenue"] == 3_690_650_989.26
    assert repaired["net_profit"] == 405_394_870.88
    assert repaired["operating_cash_flow"] == 1_247_581_972.19
    assert cache.get("fin:abstract:600001") == original_failed
    assert cache.get("fin:abstract:600002") == original_partial


def test_extract_crosscheck_record_flattens_bulk_statement_tables():
    crosscheck = {
        "merged": {
            "code": "300451",
            "period": "20260331",
            "tables": {
                "income": {
                    "营业总收入": 197_317_412.83,
                    "净利润": -79_466_551.56,
                },
                "cashflow": {
                    "经营性现金流-现金流量净额": -195_663_892.71,
                },
            },
        }
    }

    record = repair_financial_abstracts.extract_crosscheck_record(crosscheck)

    assert record == {
        "code": "300451",
        "report_date": "20260331",
        "revenue": 197_317_412.83,
        "net_profit": -79_466_551.56,
        "operating_cash_flow": -195_663_892.71,
    }


def test_backfill_from_crosschecks_repairs_locally_and_skips_incomplete_sources():
    cache = FakeCache(
        {
            "fin:abstract:300451": [{"report_date": "20260331", "roe": -2.0}],
            "fin:crosscheck:300451": {
                "merged": {
                    "code": "300451",
                    "period": "20260331",
                    "tables": {
                        "performance": {
                            "营业总收入-营业总收入": 197_317_412.83,
                            "净利润-净利润": -79_466_551.56,
                        },
                        "cashflow": {
                            "经营性现金流-现金流量净额": -195_663_892.71,
                        },
                    },
                }
            },
            "fin:abstract:600001": [{"report_date": "20260331", "roe": 3.0}],
            "fin:crosscheck:600001": {
                "merged": {
                    "code": "600001",
                    "period": "20260331",
                    "tables": {
                        "income": {"营业总收入": 10, "净利润": 1},
                    },
                }
            },
        }
    )

    result = repair_financial_abstracts.backfill_from_crosschecks(
        ["300451", "600001"],
        cache,
    )

    assert result["backfilled"] == 1
    assert result["failed"] == 1
    missing = repair_financial_abstracts.missing_required_fields(
        cache.get("fin:abstract:300451")
    )
    assert missing == []
    assert cache.get("fin:abstract:600001") == [
        {"report_date": "20260331", "roe": 3.0}
    ]


def test_backfill_from_bulk_periods_fills_only_latest_missing_fields():
    cache = FakeCache(
        {
            "fin:abstract:000563": [
                {
                    "report_date": "20260331",
                    "revenue": None,
                    "net_profit": 290_064_432.69,
                    "operating_cash_flow": 1_066_496_391.77,
                }
            ]
        }
    )
    calls = []

    def income_fetcher(period):
        calls.append(("income", period))
        return [
            {
                "股票代码": "000563",
                "营业总收入": 429_473_165.18,
                "净利润": 290_064_432.69,
            }
        ]

    def cashflow_fetcher(period):
        calls.append(("cashflow", period))
        raise AssertionError("cashflow source should not be called")

    result = repair_financial_abstracts.backfill_from_bulk_periods(
        ["000563"],
        cache,
        income_fetcher=income_fetcher,
        cashflow_fetcher=cashflow_fetcher,
    )

    assert result["backfilled"] == 1
    assert result["failed"] == 0
    assert calls == [("income", "20260331")]
    latest = cache.get("fin:abstract:000563")[0]
    assert latest["revenue"] == 429_473_165.18


def test_backfill_historical_periods_fetches_each_period_once_and_preserves_fields():
    cache = FakeCache(
        {
            "fin:abstract:300450": [
                {"report_date": "20250331", "roe": 4.2},
                {
                    "report_date": "20250630",
                    "revenue": 20,
                    "net_profit": 3,
                    "operating_cash_flow": None,
                    "roe": 5.1,
                },
            ],
            "fin:abstract:300451": [
                {"report_date": "20250331", "roe": -1.0},
            ],
        }
    )
    calls = []

    def income_fetcher(period):
        calls.append(("income", period))
        assert period == "20250331"
        return [
            {"股票代码": "300450", "营业总收入": 10, "净利润": 2},
            {"股票代码": "300451", "营业总收入": 8, "净利润": -1},
        ]

    def cashflow_fetcher(period):
        calls.append(("cashflow", period))
        values = {
            "20250331": [
                {
                    "股票代码": "300450",
                    "经营性现金流-现金流量净额": 4,
                },
                {
                    "股票代码": "300451",
                    "经营性现金流-现金流量净额": -2,
                },
            ],
            "20250630": [
                {
                    "股票代码": "300450",
                    "经营性现金流-现金流量净额": 6,
                }
            ],
        }
        return values[period]

    result = repair_financial_abstracts.backfill_historical_periods(
        ["300450", "300451"],
        cache,
        start_period="20250101",
        income_fetcher=income_fetcher,
        cashflow_fetcher=cashflow_fetcher,
        workers=1,
    )

    assert result["target_periods"] == 2
    assert result["target_records"] == 3
    assert result["completed_records"] == 3
    assert result["remaining_records"] == 0
    assert calls == [
        ("income", "20250331"),
        ("cashflow", "20250331"),
        ("cashflow", "20250630"),
    ]
    rows_450 = {
        row["report_date"]: row
        for row in cache.get("fin:abstract:300450")
    }
    assert rows_450["20250331"] == {
        "report_date": "20250331",
        "roe": 4.2,
        "code": "300450",
        "revenue": 10,
        "net_profit": 2,
        "operating_cash_flow": 4,
    }
    assert rows_450["20250630"]["roe"] == 5.1
    assert rows_450["20250630"]["operating_cash_flow"] == 6


def test_backfill_historical_periods_preserves_incomplete_row_when_source_is_empty():
    original = [{"report_date": "20250331", "roe": 1.2}]
    cache = FakeCache({"fin:abstract:600001": original})

    result = repair_financial_abstracts.backfill_historical_periods(
        ["600001"],
        cache,
        start_period="20250101",
        income_fetcher=lambda _period: [],
        cashflow_fetcher=lambda _period: [],
        workers=1,
    )

    assert result["completed_records"] == 0
    assert result["remaining_records"] == 1
    assert cache.get("fin:abstract:600001") == original


def test_backfill_historical_periods_retries_transient_source_failure():
    cache = FakeCache(
        {
            "fin:abstract:600001": [
                {"report_date": "20250331", "roe": 1.2}
            ]
        }
    )
    attempts = {"income": 0, "cashflow": 0}

    def income_fetcher(_period):
        attempts["income"] += 1
        if attempts["income"] == 1:
            raise ConnectionError("temporary income failure")
        return [
            {
                "股票代码": "600001",
                "营业总收入": 10,
                "净利润": 2,
            }
        ]

    def cashflow_fetcher(_period):
        attempts["cashflow"] += 1
        if attempts["cashflow"] == 1:
            raise ConnectionError("temporary cashflow failure")
        return [
            {
                "股票代码": "600001",
                "经营性现金流-现金流量净额": 3,
            }
        ]

    result = repair_financial_abstracts.backfill_historical_periods(
        ["600001"],
        cache,
        start_period="20250101",
        income_fetcher=income_fetcher,
        cashflow_fetcher=cashflow_fetcher,
        workers=1,
        source_retries=1,
        retry_delay_seconds=0,
    )

    assert result["completed_records"] == 1
    assert result["remaining_records"] == 0
    assert result["source_failures"] == {}
    assert attempts == {"income": 2, "cashflow": 2}


def test_backfill_historical_periods_can_limit_retry_to_selected_periods():
    cache = FakeCache(
        {
            "fin:abstract:600001": [
                {"report_date": "20191231"},
                {"report_date": "20200331"},
            ]
        }
    )
    calls = []

    def income_fetcher(period):
        calls.append(("income", period))
        return [
            {
                "股票代码": "600001",
                "营业总收入": 10,
                "净利润": 2,
            }
        ]

    def cashflow_fetcher(period):
        calls.append(("cashflow", period))
        return [
            {
                "股票代码": "600001",
                "经营性现金流-现金流量净额": 3,
            }
        ]

    result = repair_financial_abstracts.backfill_historical_periods(
        ["600001"],
        cache,
        start_period="20190101",
        periods=["20200331"],
        income_fetcher=income_fetcher,
        cashflow_fetcher=cashflow_fetcher,
        workers=1,
    )

    assert result["target_periods"] == 1
    assert result["target_records"] == 1
    assert result["completed_records"] == 1
    assert calls == [
        ("income", "20200331"),
        ("cashflow", "20200331"),
    ]
    rows = {
        row["report_date"]: row
        for row in cache.get("fin:abstract:600001")
    }
    assert "revenue" not in rows["20191231"]
    assert rows["20200331"]["revenue"] == 10


def test_audit_financial_history_aggregates_completeness_and_freshness():
    cache = FakeCache(
        {
            "fin:abstract:300450": [
                {
                    "report_date": "20251231",
                    "revenue": 10,
                    "net_profit": 2,
                    "operating_cash_flow": 3,
                },
                {
                    "report_date": "20260331",
                    "revenue": 4,
                    "net_profit": None,
                    "operating_cash_flow": 1,
                },
            ],
            "fin:abstract:688121": [
                {
                    "report_date": "20250930",
                    "revenue": 8,
                    "net_profit": 1,
                    "operating_cash_flow": -2,
                }
            ],
        }
    )

    result = repair_financial_abstracts.audit_financial_history(
        cache,
        as_of_date="20260722",
        start_period="20250101",
    )

    assert result["total_codes"] == 2
    assert result["total_periods"] == 3
    assert result["complete_periods"] == 2
    assert result["incomplete_periods"] == 1
    assert result["completeness_ratio"] == 0.666667
    assert result["latest_complete_codes"] == 1
    assert result["freshness"] == {
        "current": 1,
        "stale": 1,
        "unknown": 0,
    }
    assert result["stale_codes"] == ["688121"]


def test_resolve_history_start_uses_explicit_period_or_lookback_years():
    assert repair_financial_abstracts.resolve_history_start(
        as_of_date="20260722",
        history_years=10,
        explicit_start="",
    ) == "20160101"
    assert repair_financial_abstracts.resolve_history_start(
        as_of_date="20260722",
        history_years=10,
        explicit_start="20200101",
    ) == "20200101"
