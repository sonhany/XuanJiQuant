def quality_kwargs():
    return {
        "requested": 100,
        "completed": 99,
        "recent_coverage": 0.995,
        "trading_days": 1400,
        "latest_date_matches": True,
        "duplicate_rows": 0,
        "invalid_ohlc": 0,
        "non_positive_factors": 0,
        "unknown_st_samples": 0,
        "invalid_lifecycle_samples": 0,
        "dataset_version": "daily-pit-2020-01-01-2026-01-01",
    }


def test_quality_gate_rejects_low_coverage():
    from quant.qlib.quality_gate import check_dataset_quality

    kwargs = quality_kwargs()
    kwargs["completed"] = 97
    result = check_dataset_quality(**kwargs)

    assert result["passed"] is False
    assert "coverage_below_98pct" in result["reason_codes"]


def test_quality_gate_reports_all_hard_failures():
    from quant.qlib.quality_gate import check_dataset_quality

    result = check_dataset_quality(
        requested=100,
        completed=90,
        recent_coverage=0.90,
        trading_days=1000,
        latest_date_matches=False,
        duplicate_rows=1,
        invalid_ohlc=2,
        non_positive_factors=3,
        unknown_st_samples=4,
        invalid_lifecycle_samples=5,
        dataset_version="daily-pit-test",
    )

    assert set(result["reason_codes"]) == {
        "coverage_below_98pct",
        "recent_coverage_below_99pct",
        "trading_days_below_1200",
        "latest_date_mismatch",
        "duplicate_rows",
        "invalid_ohlc",
        "non_positive_factor",
        "unknown_st_in_training",
        "invalid_lifecycle_sample",
    }


def test_quality_gate_accepts_all_thresholds():
    from quant.qlib.quality_gate import check_dataset_quality

    result = check_dataset_quality(**quality_kwargs())

    assert result["passed"] is True
    assert result["status"] == "passed"
    assert result["reason_codes"] == []


def test_quality_report_has_stable_identity():
    from quant.qlib.quality_gate import GATE_VERSION, check_dataset_quality

    result = check_dataset_quality(**quality_kwargs())
    repeated = check_dataset_quality(**quality_kwargs())

    assert result["gate_version"] == GATE_VERSION == "qlib_phase1_gate_v1"
    assert result["dataset_version"] == quality_kwargs()["dataset_version"]
    assert result["report_id"].startswith("quality_")
    assert result["report_id"] == repeated["report_id"]
    assert len(result["report_id"]) == len("quality_") + 20


def test_lifecycle_coverage_excludes_prelisting_and_postdelisting_days():
    from quant.qlib.quality_gate import calculate_lifecycle_coverage

    coverage = calculate_lifecycle_coverage(
        trading_days=[
            "2026-01-02",
            "2026-01-05",
            "2026-01-06",
            "2026-01-07",
            "2026-01-08",
        ],
        symbols=[
            {
                "instrument": "SH600000",
                "listing_date": "2026-01-05",
                "delisting_date": "",
                "observed_dates": ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"],
            },
            {
                "instrument": "SZ000001",
                "listing_date": "",
                "delisting_date": "2026-01-06",
                "observed_dates": ["2026-01-02", "2026-01-05", "2026-01-06"],
            },
        ],
    )

    assert coverage == {
        "expected_samples": 7,
        "observed_samples": 7,
        "coverage": 1.0,
    }
