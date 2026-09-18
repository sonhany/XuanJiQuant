from scripts import daily_report


class _FakeCache:
    def get(self, key):
        if key == "paper:config":
            return {"llm": {"enabled": False, "provider": "glm"}}
        return None


def test_ai_review_falls_back_to_local_rules_when_llm_disabled(monkeypatch):
    monkeypatch.setattr(daily_report, "cache", _FakeCache())

    review = daily_report._generate_ai_review(
        {
            "account": {"total_pnl_pct": 0, "cash": 100, "total_equity": 100},
            "data": {"latest_kline_date": "20260710", "is_stale": False},
            "alerts": {"active": 0, "critical": 0},
            "positions": [],
            "risk_rejections": [],
        }
    )

    assert review["enabled"] is True
    assert review["active"] is True
    assert review["fallback"] is True
    assert review["provider"] == "local_rules"
