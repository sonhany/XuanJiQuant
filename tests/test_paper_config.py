from scripts.paper import config as paper_config


def normalize_paper_config(value):
    assert hasattr(paper_config, "normalize_paper_config"), "paper config normalizer is missing"
    return paper_config.normalize_paper_config(value)


def test_paper_config_normalizes_every_editable_field_and_percent_units():
    config = normalize_paper_config({
        "strategy_name": "ma_cross",
        "strategy_params": {"fast": "5", "slow": "20"},
        "universe": ["600519", "600519", "bad", "000001"],
        "position_size_pct": 20,
        "max_positions": "6",
        "trade_time": "14:55",
        "llm": {
            "enabled": True,
            "inherit_global": False,
            "provider": "opencode",
            "model": "deepseek-v4-flash-free",
            "mode": "decide",
        },
        "risk": {"max_position_pct": 15},
    })

    assert config["strategy_name"] == "ma_cross"
    assert config["strategy_params"] == {"fast": "5", "slow": "20"}
    assert config["universe"] == ["600519", "000001"]
    assert config["position_size_pct"] == 0.2
    assert config["max_positions"] == 6
    assert config["trade_time"] == "14:55"
    assert config["llm"]["enabled"] is True
    assert config["llm"]["inherit_global"] is False
    assert config["llm"]["provider"] == "opencode"
    assert config["llm"]["model"] == "deepseek-v4-flash-free"
    assert config["llm"]["mode"] == "decide"
    assert config["risk"]["max_position_pct"] == 0.15


def test_paper_config_invalid_values_fall_back_to_safe_defaults():
    config = normalize_paper_config({
        "universe": ["bad"],
        "position_size_pct": -1,
        "max_positions": 0,
        "trade_time": "25:99",
        "llm": {"provider": "unknown", "model": "unknown", "mode": "unknown"},
    })

    assert config["universe"]
    assert config["position_size_pct"] == 0.2
    assert config["max_positions"] == 5
    assert config["trade_time"] == "15:05"
    assert config["llm"]["provider"] == "glm"
    assert config["llm"]["mode"] == "review"


def test_paper_config_does_not_persist_runtime_derived_llm_fields():
    config = normalize_paper_config({
        "llm": {
            "effective_source": "legacy_runtime",
            "registry_version": 99,
        },
    })

    assert "effective_source" not in config["llm"]
    assert "registry_version" not in config["llm"]
