from scripts import daily_report


class _FakeCache:
    def get(self, key):
        if key == "paper:config":
            return {"llm": {"enabled": True, "provider": "glm", "timeout": 1}}
        return None


def test_ai_review_falls_back_when_llm_fails(monkeypatch):
    import scripts.llm_client as llm_client

    monkeypatch.setattr(daily_report, "cache", _FakeCache())
    monkeypatch.setattr(
        llm_client,
        "chat",
        lambda *args, **kwargs: {"success": False, "error": "HTTP Error 429: Too Many Requests"},
    )
    monkeypatch.setattr(llm_client, "get_provider_label", lambda provider: "GLM")

    review = daily_report._generate_ai_review(
        {
            "report_date": "20260706",
            "account": {"total_equity": 971129.7, "cash": 200000, "total_pnl_pct": -2.89},
            "benchmark": {},
            "positions": [{"code": "000001", "quantity": 1000, "pnl_pct": -1.2}],
            "data": {"latest_kline_date": "20260706", "is_stale": False},
            "alerts": {"active": 3, "critical": 1},
            "risk_rejections": [{}],
        }
    )

    assert review["enabled"] is True
    assert review["active"] is True
    assert review["fallback"] is True
    assert review["provider"] == "glm"
    assert "429" in review["error"]


def test_ai_review_rejects_model_meta_reasoning_and_uses_local_summary(monkeypatch):
    import scripts.llm_client as llm_client

    monkeypatch.setattr(daily_report, "cache", _FakeCache())
    monkeypatch.setattr(
        llm_client,
        "chat",
        lambda *args, **kwargs: {
            "success": True,
            "text": "3. 持仓风险可控。\n\n让我们精确重数每条要点的字数：\n要点1：组合上涨。",
        },
    )
    monkeypatch.setattr(llm_client, "get_provider_label", lambda provider: "GLM")

    review = daily_report._generate_ai_review(
        {
            "report_date": "20260806",
            "account": {"total_equity": 1_018_201.61, "cash": 471_981.86, "total_pnl_pct": 1.82},
            "benchmark": {},
            "positions": [{"code": "600817", "quantity": 22100, "pnl_pct": -0.26}],
            "data": {"latest_kline_date": "20260806", "is_stale": False},
            "alerts": {"active": 0, "critical": 0},
            "risk_rejections": [{}],
        }
    )

    assert review["fallback"] is True
    assert review["error"] == "invalid_ai_review_format"
    assert "让我们" not in review["text"]
