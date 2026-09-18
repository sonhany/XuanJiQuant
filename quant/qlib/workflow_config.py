from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any

from .features import alpha158_handler_config, alpha360_handler_config


MODEL_MATRIX = (
    ("Alpha158", "LightGBM"),
    ("Alpha360", "LightGBM"),
    ("Alpha158", "XGBoost"),
    ("Alpha158", "Linear"),
)

MODEL_CONFIGS = {
    "LightGBM": {
        "class": "LGBModel",
        "module_path": "qlib.contrib.model.gbdt",
        "kwargs": {
            "loss": "mse",
            "learning_rate": 0.0421,
            "colsample_bytree": 0.8879,
            "subsample": 0.8789,
            "lambda_l1": 205.6999,
            "lambda_l2": 580.9768,
            "max_depth": 8,
            "num_leaves": 210,
            "num_threads": 8,
        },
    },
    "XGBoost": {
        "class": "XGBModel",
        "module_path": "qlib.contrib.model.xgboost",
        "kwargs": {
            "objective": "reg:squarederror",
            "eta": 0.05,
            "max_depth": 8,
            "subsample": 0.9,
            "colsample_bytree": 0.9,
            "nthread": 8,
        },
    },
    "Linear": {
        "class": "LinearModel",
        "module_path": "qlib.contrib.model.linear",
        "kwargs": {
            "estimator": "ridge",
            "alpha": 0.001,
            "fit_intercept": True,
        },
    },
}

WINDOW_WORKFLOW_CONFIG_VERSION = "f4-qlib-window-workflow-v2"


def build_dataset_config(
    *,
    handler: str,
    instruments: str,
    segments: dict[str, tuple[str, str]],
) -> dict[str, Any]:
    if handler not in {"Alpha158", "Alpha360"}:
        raise ValueError(f"unsupported Qlib handler: {handler}")
    required = {"train", "valid", "test"}
    if set(segments) != required:
        raise ValueError("Qlib segments must contain train, valid and test")
    starts = [str(value[0]) for value in segments.values()]
    ends = [str(value[1]) for value in segments.values()]
    builder = (
        alpha158_handler_config if handler == "Alpha158" else alpha360_handler_config
    )
    handler_config = builder(
        instruments=instruments,
        start_time=min(starts),
        end_time=max(ends),
        fit_start_time=str(segments["train"][0]),
        fit_end_time=str(segments["train"][1]),
    )
    return {
        "class": "DatasetH",
        "module_path": "qlib.data.dataset",
        "kwargs": {
            "handler": handler_config,
            "segments": copy.deepcopy(segments),
        },
    }


def build_model_config(model_type: str, seed: int) -> dict[str, Any]:
    if model_type not in MODEL_CONFIGS:
        raise ValueError(f"unsupported Qlib model: {model_type}")
    config = copy.deepcopy(MODEL_CONFIGS[model_type])
    normalized_seed = int(seed)
    if model_type == "LightGBM":
        config["kwargs"].update(
            {
                "seed": normalized_seed,
                "feature_fraction_seed": normalized_seed,
                "bagging_seed": normalized_seed,
            }
        )
    elif model_type == "XGBoost":
        config["kwargs"]["seed"] = normalized_seed
    else:
        config["xuanji_metadata"] = {"seed": normalized_seed}
    return config


def build_window_workflow_config(
    *,
    candidate_id: str,
    window_id: str,
    alpha_spec_hash: str,
    handler: str,
    model_type: str,
    seed: int,
    instruments: str,
    segments: dict[str, tuple[str, str]],
    minimum_coverage: float,
    allowed_segment_dates: dict[str, tuple[str, ...]],
    allowed_segment_identities: dict[
        str, tuple[tuple[str, str], ...]
    ],
    recorder_identity: str,
) -> dict[str, Any]:
    """Build the immutable config for one F4 Qlib outer window.

    This is deliberately additive to the weekly workflow config.  All three
    segments are described here, while the window workflow boundary controls
    which segment may be predicted at each lifecycle stage.
    """

    if (
        not candidate_id
        or not window_id
        or not alpha_spec_hash
        or not recorder_identity
    ):
        raise ValueError("Qlib window identity is incomplete")
    if not math.isfinite(float(minimum_coverage)) or not (
        0.0 < float(minimum_coverage) <= 1.0
    ):
        raise ValueError("Qlib minimum coverage is invalid")
    dataset = build_dataset_config(
        handler=handler,
        instruments=instruments,
        segments=segments,
    )
    if set(allowed_segment_dates) != {"valid", "test"} or any(
        not tuple(allowed_segment_dates[segment]) for segment in ("valid", "test")
    ):
        raise ValueError("Qlib allowed segment dates are invalid")
    model = build_model_config(model_type, seed)
    return {
        "version": WINDOW_WORKFLOW_CONFIG_VERSION,
        "candidate_id": str(candidate_id),
        "window_id": str(window_id),
        "alpha_spec_hash": str(alpha_spec_hash),
        "handler": str(handler),
        "model_type": str(model_type),
        "seed": int(seed),
        "minimum_coverage": float(minimum_coverage),
        "allowed_segment_dates": {
            segment: list(allowed_segment_dates[segment])
            for segment in ("valid", "test")
        },
        "allowed_segment_identities": {
            segment: [list(identity) for identity in allowed_segment_identities.get(segment, ())]
            for segment in ("valid", "test")
        },
        "recorder_identity": str(recorder_identity),
        "dataset": dataset,
        "model": model,
    }


def build_port_analysis_config(start_time: str, end_time: str) -> dict[str, Any]:
    return {
        "executor": {
            "class": "SimulatorExecutor",
            "module_path": "qlib.backtest.executor",
            "kwargs": {"time_per_step": "day", "generate_portfolio_metrics": True},
        },
        "strategy": {
            "class": "TopkDropoutStrategy",
            "module_path": "qlib.contrib.strategy.signal_strategy",
            "kwargs": {"signal": "<PRED>", "topk": 50, "n_drop": 5},
        },
        "backtest": {
            "start_time": str(start_time),
            "end_time": str(end_time),
            "account": 100_000_000,
            "benchmark": "SH000300",
            "exchange_kwargs": {
                "freq": "day",
                "limit_threshold": 0.095,
                "deal_price": "close",
                "open_cost": 0.0005,
                "close_cost": 0.0015,
                "min_cost": 5,
            },
        },
    }


def config_sha256(config: dict[str, Any]) -> str:
    encoded = json.dumps(
        config,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
