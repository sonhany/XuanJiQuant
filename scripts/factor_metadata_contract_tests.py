from __future__ import annotations


def test_factor_meta_exposes_human_readable_chinese_names():
    import scripts.factor_runner as factor_runner

    out = factor_runner.action_meta({})
    data = out["data"]

    assert "range_pct" in data
    assert data["range_pct"]["label"] == "日内振幅"
    assert "最高价" in data["range_pct"]["desc"]
    assert "ret_5" in data
    assert data["ret_5"]["label"] == "5日动量"
    assert data["ret_5"]["category_name"]


def test_factor_definition_uses_metadata_description():
    import scripts.factor_runner as factor_runner

    assert factor_runner._factor_definition("range_pct") == "(high - low) / close"
    assert "收盘价相对20日均线" in factor_runner._factor_definition("bias_20")
