from scripts import daily_report


class FakeCache:
    def __init__(self, values):
        self.values = values

    def get(self, key):
        return self.values.get(key)


def test_cached_report_uses_authoritative_execution_account(monkeypatch):
    cache = FakeCache({})
    monkeypatch.setattr(daily_report, "cache", cache)
    monkeypatch.setattr(daily_report, "load_active_account_projection", lambda: {
        "ledger_authority": "f5",
        "account": {
            "initial_capital": 1_000_000.0,
            "cash": 685_415.36,
            "market_value": 148_036.28,
            "total_equity": 833_451.64,
            "total_pnl": -166_548.36,
            "total_pnl_pct": -16.654836,
            "updated_at": "2026-07-29 11:05:28",
        },
        "positions": [{
            "code": "000507",
            "quantity": 29_141,
            "available_qty": 29_141,
            "avg_price": 4.84,
            "current_price": 5.08,
        }],
        "orders": [],
        "trades": [],
    })
    cached = {
        "generated_at": "2026-07-28 17:13:52",
        "account": {
            "initial_capital": 1_000_000.0,
            "cash": 900.0,
            "market_value": 0.0,
            "total_equity": 900.0,
            "total_pnl": -999_100.0,
            "total_pnl_pct": -99.91,
            "position_count": 0,
        },
        "positions": [],
        "ai_review": {
            "enabled": True,
            "active": True,
            "provider": "glm",
            "text": "总权益为900元，累计亏损99.91%",
        },
    }

    reconciled = daily_report.reconcile_report_with_execution(cached, cache)

    assert cached["account"]["total_equity"] == 900.0
    assert reconciled["account"]["cash"] == 685_415.36
    assert reconciled["account"]["total_equity"] == 833_451.64
    assert reconciled["account"]["total_pnl"] == -166_548.36
    assert reconciled["account"]["position_count"] == 1
    assert reconciled["positions"][0]["code"] == "000507"
    assert reconciled["account_source"] == "f5_ledger"
    assert reconciled["ledger_authority"] == "f5"
    assert reconciled["account_as_of"] == "2026-07-29 11:05:28"
    assert reconciled["ai_review"]["active"] is False
    assert reconciled["ai_review"]["stale"] is True
    assert reconciled["historical_ai_review"]["text"].startswith("总权益为900元")
