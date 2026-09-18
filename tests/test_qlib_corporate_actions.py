import pytest


def test_reconcile_factor_uses_positive_tdx_factor():
    from quant.qlib.corporate_actions import reconcile_adjustment_rows

    rows = reconcile_adjustment_rows(
        raw=[{"datetime": "2026-01-02", "close": 10.0, "factor": 0.5}],
        front=[{"datetime": "2026-01-02", "close": 5.0}],
        baostock_factors=[],
    )

    assert rows[0]["factor"] == 0.5
    assert rows[0]["factor_source"] == "tdxquant"
    assert rows[0]["front_price_deviation"] == pytest.approx(0.0)


def test_reconcile_factor_uses_derived_factor_when_sources_are_missing():
    from quant.qlib.corporate_actions import reconcile_adjustment_rows

    rows = reconcile_adjustment_rows(
        raw=[{"datetime": "2026-01-02", "close": 10.0}],
        front=[{"datetime": "2026-01-02", "close": 8.0}],
        baostock_factors=[],
    )

    assert rows[0]["factor"] == pytest.approx(0.8)
    assert rows[0]["factor_source"] == "derived"


def test_reconcile_factor_rejects_non_positive_values():
    from quant.qlib.corporate_actions import validate_adjustment_rows

    report = validate_adjustment_rows(
        [{"datetime": "2026-01-02", "close": 10.0, "factor": 0.0}]
    )

    assert report["passed"] is False
    assert "non_positive_factor" in report["reason_codes"]


def test_front_price_deviation_over_one_percent_is_reported():
    from quant.qlib.corporate_actions import compare_front_prices

    report = compare_front_prices(
        raw_close=10.0,
        factor=0.5,
        observed_front_close=5.2,
        tolerance=0.01,
    )

    assert report["deviation"] == pytest.approx(0.04)
    assert report["passed"] is False


def test_reconcile_uses_observed_derived_factor_when_tdx_factor_misses_front_price():
    from quant.qlib.corporate_actions import reconcile_adjustment_rows

    rows = reconcile_adjustment_rows(
        raw=[{"datetime": "2021-08-02", "close": 18.01, "factor": 0.805427}],
        front=[{"datetime": "2021-08-02", "close": 15.57}],
        baostock_factors=[],
    )

    assert rows[0]["factor"] == pytest.approx(15.57 / 18.01)
    assert rows[0]["factor_source"] == "derived"
    assert rows[0]["tdxquant_factor"] == pytest.approx(0.805427)
    assert rows[0]["front_price_valid"] is True
