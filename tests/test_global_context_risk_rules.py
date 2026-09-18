from scripts.global_context import assess_market_risk


def test_nasdaq_upside_jump_is_caution_not_high_risk_block():
    result = assess_market_risk(
        {"gb_$ndx": {"chg_pct": 3.32}},
        {},
        {"quotes": []},
    )

    assert result["risk_level"] == "medium"
    assert result["trade_policy"] == "reduce_only"
    assert result["risk_signals"] == ["纳斯达克上涨3.3%"]


def test_nasdaq_downside_jump_remains_high_risk_block():
    result = assess_market_risk(
        {"gb_$ndx": {"chg_pct": -3.32}},
        {},
        {"quotes": []},
    )

    assert result["risk_level"] == "high"
    assert result["trade_policy"] == "no_new_position"
    assert result["risk_signals"] == ["纳斯达克下跌3.3%"]
