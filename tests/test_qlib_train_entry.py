from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
TRAIN_PATH = ROOT / "scripts" / "qlib_train.py"


def load_train():
    spec = importlib.util.spec_from_file_location("qlib_train_contract", TRAIN_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_six_year_dataset_uses_market_universe_without_benchmark():
    train = load_train()

    assert train._research_instruments("a_share_6y_daily") == "market"
    assert train._research_instruments("a_share_1y_daily") == "all"


def test_chronological_segments_do_not_overlap():
    train = load_train()
    calendar = pd.date_range("2020-01-01", periods=100, freq="B")
    segments = train.chronological_segments(calendar)
    assert segments["train"][1] < segments["valid"][0]
    assert segments["valid"][1] < segments["test"][0]
    assert segments["train"][0] == "2020-01-01"
    assert segments["test"][1] == calendar[-2].strftime("%Y-%m-%d")
    assert calendar[-1].strftime("%Y-%m-%d") not in {
        boundary for segment in segments.values() for boundary in segment
    }


def test_chronological_segments_require_enough_history():
    train = load_train()
    with pytest.raises(ValueError, match="at least 60"):
        train.chronological_segments(pd.date_range("2020-01-01", periods=30, freq="B"))


def test_artifact_manifest_requires_matching_experiment_id(tmp_path):
    train = load_train()
    (tmp_path / "model.txt").write_text("model", encoding="utf-8")
    (tmp_path / "metrics.json").write_text(
        '{"experiment_id":"exp-1"}',
        encoding="utf-8",
    )
    (tmp_path / "predictions.parquet").write_bytes(b"data")
    (tmp_path / "report.json").write_text(
        '{"experiment_id":"exp-2"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="experiment ID mismatch"):
        train.validate_artifact_bundle(tmp_path, "exp-1")


def test_prepare_frames_keeps_missing_features_when_label_is_valid():
    train = load_train()
    index = pd.MultiIndex.from_product(
        [[pd.Timestamp("2020-01-02"), pd.Timestamp("2020-01-03")], ["SH600000"]],
        names=["datetime", "instrument"],
    )
    learn_frame = pd.DataFrame(
        {
            ("feature", "F1"): [1.0, np.nan],
            ("feature", "F2"): [np.nan, 2.0],
            ("label", "LABEL0"): [1.0, 2.0],
        },
        index=index,
    )
    infer_frame = learn_frame.copy()
    infer_frame[("label", "LABEL0")] = [0.01, 0.02]

    class FakeDataset:
        def prepare(self, *_args, **_kwargs):
            data_key = _kwargs.get("data_key")
            return (infer_frame if data_key == "infer" else learn_frame).copy()

    dataset, label = train._prepare_frames(FakeDataset(), lambda *_: None)
    assert len(dataset["train_x"]) == 2
    assert label.tolist() == [0.01, 0.02]


def test_training_preserves_existing_dataset_coverage_metadata(tmp_path):
    train = load_train()
    existing = {
        "id": "a_share_1y_daily",
        "status": "incomplete",
        "instruments": 5203,
        "rows": 1298195,
        "coverage": 0.9996,
        "created_at": "2026-07-12T00:00:00+00:00",
        "metadata": {"failed": 2},
    }

    row = train._dataset_registry_row(
        existing=existing,
        dataset_id="a_share_1y_daily",
        preset="one-year",
        provider_uri=tmp_path,
        segments={
            "train": ("2025-06-27", "2026-01-01"),
            "valid": ("2026-01-02", "2026-04-01"),
            "test": ("2026-04-02", "2026-07-10"),
        },
        now="2026-07-12T00:00:00+00:00",
    )

    assert row["status"] == "incomplete"
    assert row["instruments"] == 5203
    assert row["rows"] == 1298195
    assert row["coverage"] == pytest.approx(0.9996)
    assert row["metadata"]["failed"] == 2
    assert row["metadata"]["preset"] == "one-year"


def test_six_year_walk_forward_preset_is_recognized(tmp_path, monkeypatch):
    train = load_train()
    monkeypatch.setattr(train, "resolve_data_path", lambda *parts: tmp_path.joinpath(*parts))

    with pytest.raises(RuntimeError, match="Qlib bin dataset is not ready"):
        train.run_preset("six-year-walk-forward")


def test_training_entry_uses_official_workflow_bridge_not_custom_trainer():
    source = TRAIN_PATH.read_text(encoding="utf-8")

    assert "from quant.qlib.workflow_bridge import" in source
    assert "run_workflow(" in source
    assert "import_workflow_result(result, store)" in source
    assert "from quant.qlib.trainer import train_lightgbm" not in source


def test_recorder_tracking_backend_is_project_local_sqlite(tmp_path, monkeypatch):
    train = load_train()
    monkeypatch.setattr(
        train,
        "resolve_data_path",
        lambda *parts: tmp_path.joinpath(*parts),
    )

    uri = train._recorder_uri()

    assert uri == f"sqlite:///{(tmp_path / 'mlflow.db').resolve().as_posix()}"
