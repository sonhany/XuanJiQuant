import importlib.util
from pathlib import Path


def main():
    module_path = Path(__file__).with_name("daily_report.py")
    spec = importlib.util.spec_from_file_location("daily_report", module_path)
    daily_report = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(daily_report)

    rows = daily_report._position_details(
        {
            "600519": {
                "quantity": 200,
                "avg_price": 100.0,
                "current_price": 99.0,
                "available_qty": 100,
            }
        },
        quotes={
            "sh600519": {
                "name": "Kweichow Moutai",
                "price": 101.23,
                "amount": 123456789.0,
                "chg_pct": 1.25,
            }
        },
        orders=[
            {
                "code": "600519",
                "direction": "buy",
                "quantity": 200,
                "status": "filled",
                "filled_price": 100.5,
                "created_at": "2026-07-07 09:31:00",
            }
        ],
        trades=[
            {
                "code": "600519",
                "direction": "buy",
                "quantity": 200,
                "price": 100.5,
                "timestamp": "2026-07-07 09:31:02",
            }
        ],
        today="2026-07-07",
    )

    assert rows, "position detail should not be empty"
    row = rows[0]
    assert row["code"] == "600519"
    assert row["name"] == "Kweichow Moutai"
    assert row["realtime_price"] == 101.23
    assert row["current_price"] == 101.23
    assert row["amount"] == 123456789.0
    assert row["chg_pct"] == 1.25
    assert row["market_value"] == 20246.0
    assert row["trade_count"] == 1
    assert row["order_count"] == 1
    assert row["trade_records"], "trade records should be embedded in position detail"
    assert row["trade_records"][0]["type"] == "trade"
    assert row["trade_records"][0]["direction"] == "buy"

    fallback_rows = daily_report._position_details(
        {
            "000001": {
                "quantity": 100,
                "avg_price": 10.0,
                "current_price": 10.0,
            }
        },
        quotes={},
        orders=[],
        trades=[
            {
                "code": "000001",
                "direction": "buy",
                "quantity": 100,
                "price": 10.0,
                "timestamp": "2026-07-06 13:01:00",
            }
        ],
        today="2026-07-07",
    )
    assert fallback_rows[0]["trade_records"], "position detail should fall back to latest records when there is no same-day trade"

    print("daily report position contract tests passed")


if __name__ == "__main__":
    main()
