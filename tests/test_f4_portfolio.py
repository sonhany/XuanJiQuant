from quant.strategy.portfolio import PortfolioPolicy, build_target_weights


def test_top20_weights_obey_single_name_and_industry_caps():
    rows = [
        {"code": f"{i:06d}", "score": 100 - i, "industry": f"I{i % 5}"}
        for i in range(30)
    ]
    result = build_target_weights(rows, PortfolioPolicy())
    assert len(result.weights) == 20
    assert max(result.weights.values()) <= 0.10
    totals = {}
    for row in rows:
        totals[row["industry"]] = totals.get(row["industry"], 0) + result.weights.get(
            row["code"], 0
        )
    assert max(totals.values()) <= 0.25 + 1e-12
    assert sum(result.weights.values()) <= 1.0


def test_unknown_industry_does_not_bypass_cap():
    rows = [
        {"code": f"{i:06d}", "score": 100 - i, "industry": ""}
        for i in range(30)
    ]
    result = build_target_weights(rows, PortfolioPolicy())
    assert sum(result.weights.values()) <= 0.25 + 1e-12
    assert result.cash_weight >= 0.75 - 1e-12
    assert result.exclusions["industry_cap"] == 15


def test_scores_have_stable_code_tie_break():
    rows = [
        {"code": "600002", "score": 1.0, "industry": "A"},
        {"code": "600001", "score": 1.0, "industry": "B"},
    ]
    result = build_target_weights(rows, PortfolioPolicy(top_k=1))
    assert list(result.weights) == ["600001"]
