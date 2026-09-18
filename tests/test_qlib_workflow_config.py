import pytest

from quant.qlib.workflow_config import (
    MODEL_MATRIX,
    build_dataset_config,
    build_model_config,
    build_port_analysis_config,
    config_sha256,
)


def test_phase1_matrix_is_bounded():
    assert MODEL_MATRIX == (
        ("Alpha158", "LightGBM"),
        ("Alpha360", "LightGBM"),
        ("Alpha158", "XGBoost"),
        ("Alpha158", "Linear"),
    )


@pytest.mark.parametrize("handler", ["Alpha158", "Alpha360"])
def test_dataset_config_uses_future_five_day_label(handler):
    config = build_dataset_config(
        handler=handler,
        instruments="all",
        segments={
            "train": ("2020-01-01", "2022-12-31"),
            "valid": ("2023-01-01", "2023-12-31"),
            "test": ("2024-01-01", "2024-12-31"),
        },
    )

    assert config["kwargs"]["handler"]["class"] == handler
    assert config["kwargs"]["handler"]["kwargs"]["label"] == [
        "Ref($close, -5) / $close - 1"
    ]


def test_model_seed_and_official_topk_config():
    lightgbm = build_model_config("LightGBM", 42)
    xgboost = build_model_config("XGBoost", 43)
    linear = build_model_config("Linear", 44)
    port = build_port_analysis_config("2024-01-01", "2024-12-31")

    assert lightgbm["kwargs"]["seed"] == 42
    assert lightgbm["kwargs"]["feature_fraction_seed"] == 42
    assert lightgbm["kwargs"]["bagging_seed"] == 42
    assert xgboost["kwargs"]["seed"] == 43
    assert linear["kwargs"]["estimator"] == "ridge"
    assert linear["xuanji_metadata"]["seed"] == 44
    assert port["strategy"]["class"] == "TopkDropoutStrategy"
    assert port["strategy"]["kwargs"] == {
        "signal": "<PRED>",
        "topk": 50,
        "n_drop": 5,
    }
    assert port["executor"]["class"] == "SimulatorExecutor"
    assert port["backtest"]["benchmark"] == "SH000300"
    assert port["backtest"]["exchange_kwargs"] == {
        "freq": "day",
        "limit_threshold": 0.095,
        "deal_price": "close",
        "open_cost": 0.0005,
        "close_cost": 0.0015,
        "min_cost": 5,
    }
    assert config_sha256({"a": 1, "b": 2}) == config_sha256({"b": 2, "a": 1})


def test_unapproved_handler_and_model_are_rejected():
    segments = {
        "train": ("2020-01-01", "2022-12-31"),
        "valid": ("2023-01-01", "2023-12-31"),
        "test": ("2024-01-01", "2024-12-31"),
    }

    with pytest.raises(ValueError, match="unsupported Qlib handler"):
        build_dataset_config(handler="Alpha999", instruments="all", segments=segments)
    with pytest.raises(ValueError, match="unsupported Qlib model"):
        build_model_config("NeuralUnknown", 42)
