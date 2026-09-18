from quant.data.financial_quality import (
    analyze_financial_history,
    expected_financial_period,
)


def test_analyze_financial_history_reports_completeness_and_current_freshness():
    result = analyze_financial_history(
        [
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
        as_of_date="20260722",
    )

    assert result["completeness"] == {
        "status": "partial",
        "complete_periods": 1,
        "total_periods": 2,
        "incomplete_periods": 1,
        "ratio": 0.5,
        "latest_complete": False,
        "latest_missing_fields": ["net_profit"],
        "missing_by_field": {
            "revenue": 0,
            "net_profit": 1,
            "operating_cash_flow": 0,
        },
    }
    assert result["freshness"] == {
        "status": "current",
        "as_of_date": "20260722",
        "latest_period": "20260331",
        "expected_period": "20260331",
        "lag_quarters": 0,
    }
    assert result["coverage"] == {
        "start_period": "20251231",
        "end_period": "20260331",
    }


def test_expected_financial_period_follows_a_share_filing_windows():
    assert expected_financial_period("20260115") == "20250930"
    assert expected_financial_period("20260430") == "20250930"
    assert expected_financial_period("20260501") == "20260331"
    assert expected_financial_period("20260831") == "20260331"
    assert expected_financial_period("20260901") == "20260630"
    assert expected_financial_period("20261031") == "20260630"
    assert expected_financial_period("20261101") == "20260930"


def test_analyze_financial_history_marks_old_latest_period_stale():
    result = analyze_financial_history(
        [
            {
                "report_date": "20250930",
                "revenue": 10,
                "net_profit": 2,
                "operating_cash_flow": 3,
            }
        ],
        as_of_date="20260722",
    )

    assert result["freshness"]["status"] == "stale"
    assert result["freshness"]["expected_period"] == "20260331"
    assert result["freshness"]["lag_quarters"] == 2


def test_analyze_financial_history_handles_empty_history():
    result = analyze_financial_history([], as_of_date="20260722")

    assert result["completeness"]["status"] == "missing"
    assert result["completeness"]["ratio"] == 0
    assert result["freshness"]["status"] == "unknown"
    assert result["coverage"] == {
        "start_period": "",
        "end_period": "",
    }
