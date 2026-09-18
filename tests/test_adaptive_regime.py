from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import warnings
from pathlib import Path
from types import SimpleNamespace

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.exceptions import ConvergenceWarning

pytest.importorskip("hmmlearn")

from quant.qlib import regime_model
from quant.qlib.regime_model import (
    REGIME_FEATURES,
    map_hidden_states,
    train_regime_model,
)

ROOT = Path(__file__).resolve().parents[1]
ADAPTIVE_REGIME_PATH = ROOT / "scripts" / "adaptive_regime.py"


def load_adaptive_regime():
    spec = importlib.util.spec_from_file_location(
        "adaptive_regime_contract",
        ADAPTIVE_REGIME_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def regime_frame(rows: int = 360) -> pd.DataFrame:
    segment = rows // 3
    remainder = rows - segment * 3
    risk_on = segment + remainder
    index = pd.date_range("2020-01-01", periods=rows, freq="B")
    rng = np.random.default_rng(7)
    return pd.DataFrame(
        {
            "ret_20": np.r_[
                rng.normal(0.05, 0.006, risk_on),
                rng.normal(0.00, 0.006, segment),
                rng.normal(-0.06, 0.008, segment),
            ],
            "realized_vol_20": np.r_[
                rng.normal(0.10, 0.006, risk_on),
                rng.normal(0.18, 0.008, segment),
                rng.normal(0.35, 0.012, segment),
            ],
            "breadth": np.r_[
                rng.normal(0.70, 0.02, risk_on),
                rng.normal(0.50, 0.02, segment),
                rng.normal(0.25, 0.02, segment),
            ],
        },
        index=index,
    )


def _canonical_metadata_sha256(metadata: dict) -> str:
    clean = dict(metadata)
    clean.pop("metadata_sha256", None)
    payload = json.dumps(
        clean,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_pointer_and_generation_metadata(root: Path, metadata: dict) -> None:
    updated = dict(metadata)
    updated["metadata_sha256"] = _canonical_metadata_sha256(updated)
    content = (
        json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    )
    (root / "regime-latest.json").write_text(content, encoding="utf-8")
    generation_metadata = (
        root
        / "generations"
        / updated["generation_id"]
        / "metadata.json"
    )
    generation_metadata.write_text(content, encoding="utf-8")


def _load_current(root: Path, monkeypatch):
    monkeypatch.setattr(regime_model, "REGIME_ROOT", root)
    return regime_model.load_current_regime_model()


def test_three_states_publish_generation_pointer_and_exact_hash(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "regime-latest.joblib"

    metadata = train_regime_model(
        regime_frame(),
        feature_names=list(REGIME_FEATURES),
        output_path=target,
        random_state=7,
    )

    pointer_path = tmp_path / "regime-latest.json"
    pointer_bytes = pointer_path.read_bytes()
    pointer = json.loads(pointer_bytes.decode("utf-8"))
    generation = tmp_path / "generations" / pointer["generation_id"]
    artifact_path = generation / "regime.joblib"
    generation_metadata_path = generation / "metadata.json"
    persisted = artifact_path.read_bytes()
    loaded = _load_current(tmp_path, monkeypatch)
    digest = hashlib.sha256(persisted).hexdigest()

    assert metadata == pointer
    assert pointer["metadata_sha256"] == _canonical_metadata_sha256(pointer)
    assert generation_metadata_path.read_bytes() == pointer_bytes
    assert metadata["artifact_sha256"] == digest
    assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
    assert loaded["artifact_path"] == artifact_path
    assert loaded["metadata"] == metadata
    assert loaded["artifact"]["feature_names"] == list(REGIME_FEATURES)
    assert set(metadata["state_mapping"].values()) == {
        "risk_on",
        "range",
        "stress",
    }
    assert metadata["training_rows"] == 360
    assert sum(metadata["state_counts"].values()) == 360
    assert len(metadata["transition_matrix"]) == 3
    assert all(len(row) == 3 for row in metadata["transition_matrix"])
    assert metadata["converged"] is True
    assert {
        "python",
        "numpy",
        "pandas",
        "scikit_learn",
        "hmmlearn",
        "joblib",
    } <= set(metadata["dependency_versions"])


def test_state_mapping_uses_return_and_volatility():
    mapping = map_hidden_states(
        {
            0: {"ret_20": 0.04, "realized_vol_20": 0.10},
            1: {"ret_20": 0.00, "realized_vol_20": 0.18},
            2: {"ret_20": -0.05, "realized_vol_20": 0.35},
        }
    )

    assert mapping == {0: "risk_on", 1: "range", 2: "stress"}


def test_state_mapping_is_deterministic_under_exact_ties():
    tied = {
        9: {"ret_20": 0.01, "realized_vol_20": 0.20},
        3: {"ret_20": 0.01, "realized_vol_20": 0.20},
        6: {"ret_20": 0.01, "realized_vol_20": 0.20},
    }

    assert map_hidden_states(tied) == {
        3: "risk_on",
        6: "stress",
        9: "range",
    }
    assert map_hidden_states(dict(reversed(list(tied.items())))) == {
        3: "risk_on",
        6: "stress",
        9: "range",
    }


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda frame: frame.iloc[:251], "at least 252"),
        (
            lambda frame: frame.assign(
                ret_20=lambda value: value["ret_20"].mask(
                    value.index == value.index[20],
                    np.inf,
                )
            ),
            "finite",
        ),
        (lambda frame: frame.iloc[::-1], "time-ordered"),
        (
            lambda frame: frame.set_axis(
                frame.index.where(frame.index != frame.index[1], frame.index[0])
            ),
            "unique",
        ),
    ],
)
def test_training_rejects_invalid_rows_without_publishing(
    tmp_path,
    mutator,
    message,
):
    target = tmp_path / "regime-latest.joblib"

    with pytest.raises(ValueError, match=message):
        train_regime_model(
            mutator(regime_frame()),
            feature_names=list(REGIME_FEATURES),
            output_path=target,
        )

    assert not target.exists()
    assert not target.with_suffix(".json").exists()
    assert not (tmp_path / "generations").exists()


def test_training_rejects_changed_feature_order(tmp_path):
    with pytest.raises(ValueError, match="fixed feature order"):
        train_regime_model(
            regime_frame(),
            feature_names=["breadth", "ret_20", "realized_vol_20"],
            output_path=tmp_path / "regime-latest.joblib",
        )


class FakeHMM:
    def __init__(
        self,
        *,
        states: np.ndarray,
        converged: bool = True,
        warning: bool = False,
        logging_warning: bool = False,
        history: tuple[float, ...] = (1.0, 1.00001),
        iterations: int = 10,
        predict_proba_error: bool = False,
        **_: object,
    ):
        self._states = states
        self._warning = warning
        self._logging_warning = logging_warning
        self._predict_proba_error = predict_proba_error
        self.monitor_ = SimpleNamespace(
            converged=converged,
            history=history,
            iter=iterations,
            n_iter=300,
            tol=1e-4,
        )
        self.n_iter = 300
        self.tol = 1e-4
        self.transmat_ = np.eye(3)

    def fit(self, values):
        if self._warning:
            warnings.warn("did not converge", ConvergenceWarning)
        if self._logging_warning:
            logging.getLogger("hmmlearn.base").warning(
                "Model is not converging"
            )
        assert len(values) == len(self._states)
        return self

    def predict(self, values):
        assert len(values) == len(self._states)
        return self._states

    def predict_proba(self, values):
        if self._predict_proba_error:
            raise ValueError("corrupt probability model")
        probabilities = np.full((len(values), 3), 0.1)
        probabilities[
            np.arange(len(values)),
            self._states[: len(values)],
        ] = 0.8
        return probabilities


def test_training_rejects_convergence_warning(tmp_path, monkeypatch):
    rows = len(regime_frame())
    monkeypatch.setattr(
        regime_model,
        "GaussianHMM",
        lambda **kwargs: FakeHMM(
            states=np.tile(np.arange(3), rows // 3),
            warning=True,
            **kwargs,
        ),
    )

    with pytest.raises(RuntimeError, match="convergence warning"):
        train_regime_model(
            regime_frame(),
            feature_names=list(REGIME_FEATURES),
            output_path=tmp_path / "regime-latest.joblib",
        )


def test_training_rejects_non_converged_model(tmp_path, monkeypatch):
    rows = len(regime_frame())
    monkeypatch.setattr(
        regime_model,
        "GaussianHMM",
        lambda **kwargs: FakeHMM(
            states=np.tile(np.arange(3), rows // 3),
            converged=False,
            **kwargs,
        ),
    )

    with pytest.raises(RuntimeError, match="did not converge"):
        train_regime_model(
            regime_frame(),
            feature_names=list(REGIME_FEATURES),
            output_path=tmp_path / "regime-latest.joblib",
        )


def test_training_rejects_hmmlearn_logging_convergence_warning(
    tmp_path,
    monkeypatch,
):
    rows = len(regime_frame())
    monkeypatch.setattr(
        regime_model,
        "GaussianHMM",
        lambda **kwargs: FakeHMM(
            states=np.tile(np.arange(3), rows // 3),
            logging_warning=True,
            **kwargs,
        ),
    )

    with pytest.raises(RuntimeError, match="convergence warning"):
        train_regime_model(
            regime_frame(),
            feature_names=list(REGIME_FEATURES),
            output_path=tmp_path / "regime-latest.joblib",
        )


def test_training_rejects_max_iterations_without_tolerance(
    tmp_path,
    monkeypatch,
):
    rows = len(regime_frame())
    monkeypatch.setattr(
        regime_model,
        "GaussianHMM",
        lambda **kwargs: FakeHMM(
            states=np.tile(np.arange(3), rows // 3),
            converged=True,
            history=(1.0, 2.0),
            iterations=300,
            **kwargs,
        ),
    )

    with pytest.raises(RuntimeError, match="did not converge"):
        train_regime_model(
            regime_frame(),
            feature_names=list(REGIME_FEATURES),
            output_path=tmp_path / "regime-latest.joblib",
        )


def test_training_rejects_insufficient_state_support(tmp_path, monkeypatch):
    rows = len(regime_frame())
    states = np.r_[np.zeros(rows - 2, dtype=int), 1, 2]
    monkeypatch.setattr(
        regime_model,
        "GaussianHMM",
        lambda **kwargs: FakeHMM(states=states, **kwargs),
    )

    with pytest.raises(RuntimeError, match="insufficient state support"):
        train_regime_model(
            regime_frame(),
            feature_names=list(REGIME_FEATURES),
            output_path=tmp_path / "regime-latest.joblib",
        )


def test_reload_validation_failure_preserves_existing_artifacts(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "regime-latest.joblib"
    previous = train_regime_model(
        regime_frame(),
        feature_names=list(REGIME_FEATURES),
        output_path=target,
        random_state=7,
    )
    original_pointer = target.with_suffix(".json").read_bytes()
    real_load = regime_model.joblib.load

    def reject_staged(path):
        if ".staging-" in str(path):
            raise ValueError("staged artifact rejected")
        return real_load(path)

    monkeypatch.setattr(regime_model.joblib, "load", reject_staged)

    with pytest.raises(RuntimeError, match="reload validation failed"):
        train_regime_model(
            regime_frame(),
            feature_names=list(REGIME_FEATURES),
            output_path=target,
            random_state=8,
        )

    assert target.with_suffix(".json").read_bytes() == original_pointer
    loaded = _load_current(tmp_path, monkeypatch)
    assert loaded["metadata"]["generation_id"] == previous["generation_id"]


def test_reloaded_model_must_execute_probability_inference(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "regime-latest.joblib"
    rows = len(regime_frame())
    monkeypatch.setattr(
        regime_model,
        "GaussianHMM",
        lambda **kwargs: FakeHMM(
            states=np.tile(np.arange(3), rows // 3),
            predict_proba_error=True,
            **kwargs,
        ),
    )

    with pytest.raises(RuntimeError, match="reload validation failed"):
        train_regime_model(
            regime_frame(),
            feature_names=list(REGIME_FEATURES),
            output_path=target,
        )

    assert not target.exists()
    assert not target.with_suffix(".json").exists()


class SimulatedProcessCrash(BaseException):
    pass


@pytest.mark.parametrize("crash_type", [KeyboardInterrupt, SimulatedProcessCrash])
def test_crash_before_pointer_commit_keeps_previous_generation_readable(
    tmp_path,
    monkeypatch,
    crash_type,
):
    target = tmp_path / "regime-latest.joblib"
    previous = train_regime_model(
        regime_frame(),
        feature_names=list(REGIME_FEATURES),
        output_path=target,
        random_state=7,
    )
    pointer_path = target.with_suffix(".json")
    original_pointer = pointer_path.read_bytes()
    original_loaded = _load_current(tmp_path, monkeypatch)
    real_replace = regime_model.os.replace

    def crash_at_pointer_commit(source, destination):
        if Path(destination) == pointer_path:
            raise crash_type("simulated process crash before pointer commit")
        return real_replace(source, destination)

    monkeypatch.setattr(regime_model.os, "replace", crash_at_pointer_commit)

    with pytest.raises(crash_type, match="before pointer commit"):
        train_regime_model(
            regime_frame().assign(
                breadth=lambda frame: frame["breadth"] * 0.97
            ),
            feature_names=list(REGIME_FEATURES),
            output_path=target,
            random_state=8,
        )

    assert pointer_path.read_bytes() == original_pointer
    loaded = _load_current(tmp_path, monkeypatch)
    assert loaded["metadata"]["generation_id"] == previous["generation_id"]
    assert loaded["metadata"] == original_loaded["metadata"]
    assert hashlib.sha256(target.read_bytes()).hexdigest() != previous[
        "artifact_sha256"
    ]


def test_pointer_self_hash_tampering_fails_closed(tmp_path, monkeypatch):
    target = tmp_path / "regime-latest.joblib"
    train_regime_model(
        regime_frame(),
        feature_names=list(REGIME_FEATURES),
        output_path=target,
    )
    pointer_path = target.with_suffix(".json")
    tampered = json.loads(pointer_path.read_text(encoding="utf-8"))
    tampered["training_rows"] += 1
    pointer_path.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(ValueError, match="metadata hash mismatch"):
        _load_current(tmp_path, monkeypatch)


def test_pointer_cannot_escape_fixed_generation_root(tmp_path, monkeypatch):
    target = tmp_path / "regime-latest.joblib"
    metadata = train_regime_model(
        regime_frame(),
        feature_names=list(REGIME_FEATURES),
        output_path=target,
    )
    metadata["generation_id"] = "../outside"
    metadata["metadata_sha256"] = _canonical_metadata_sha256(metadata)
    target.with_suffix(".json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="generation_id"):
        _load_current(tmp_path, monkeypatch)


def test_artifact_byte_tampering_fails_before_joblib_load(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "regime-latest.joblib"
    metadata = train_regime_model(
        regime_frame(),
        feature_names=list(REGIME_FEATURES),
        output_path=target,
    )
    artifact_path = (
        tmp_path
        / "generations"
        / metadata["generation_id"]
        / "regime.joblib"
    )
    artifact_path.write_bytes(artifact_path.read_bytes() + b"tamper")
    monkeypatch.setattr(
        regime_model.joblib,
        "load",
        lambda *_: pytest.fail("tampered artifact must not be deserialized"),
    )

    with pytest.raises(ValueError, match="artifact hash mismatch"):
        _load_current(tmp_path, monkeypatch)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda metadata: metadata["state_counts"].update({"3": 1}),
        lambda metadata: metadata["state_mapping"].pop("2"),
        lambda metadata: metadata["state_means"].update(
            {"3": metadata["state_means"]["2"]}
        ),
        lambda metadata: metadata.update(
            {
                "training_start": metadata["training_end"],
                "training_end": metadata["training_start"],
            }
        ),
        lambda metadata: metadata["transition_matrix"].append([0.0, 0.0, 1.0]),
        lambda metadata: metadata.update({"converged": False}),
    ],
)
def test_pointer_strict_metadata_validation_rejects_malformed_state_contract(
    tmp_path,
    monkeypatch,
    mutation,
):
    target = tmp_path / "regime-latest.joblib"
    metadata = train_regime_model(
        regime_frame(),
        feature_names=list(REGIME_FEATURES),
        output_path=target,
    )
    mutation(metadata)
    _write_pointer_and_generation_metadata(tmp_path, metadata)

    with pytest.raises(ValueError):
        _load_current(tmp_path, monkeypatch)


def test_loaded_artifact_state_keys_must_be_exactly_zero_one_two(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "regime-latest.joblib"
    metadata = train_regime_model(
        regime_frame(),
        feature_names=list(REGIME_FEATURES),
        output_path=target,
    )
    generation = tmp_path / "generations" / metadata["generation_id"]
    artifact_path = generation / "regime.joblib"
    artifact = joblib.load(artifact_path)
    artifact["state_mapping"][3] = "stress"
    joblib.dump(artifact, artifact_path)
    metadata["artifact_sha256"] = hashlib.sha256(
        artifact_path.read_bytes()
    ).hexdigest()
    _write_pointer_and_generation_metadata(tmp_path, metadata)

    with pytest.raises(ValueError, match="state keys"):
        _load_current(tmp_path, monkeypatch)


def test_market_frame_from_fixed_dataset_is_finite_and_time_ordered(tmp_path):
    module = load_adaptive_regime()
    raw = tmp_path / "datasets" / "a_share_6y_daily" / "raw"
    raw.mkdir(parents=True)
    dates = pd.date_range("2024-01-02", periods=285, freq="B")
    for offset, symbol in enumerate(("SH600000", "SZ000001", "SZ300750")):
        closes = 10 + offset + np.cumsum(
            np.sin(np.arange(len(dates)) / 13 + offset) * 0.03 + 0.02
        )
        rows = [
            {
                "datetime": day.strftime("%Y-%m-%d"),
                "close": float(close),
                "amount": 1_000_000 + index * 100,
                "tradable": 1,
                "listed": 1,
                "delisted": 0,
            }
            for index, (day, close) in enumerate(zip(dates, closes))
        ]
        (raw / f"{symbol}.json").write_text(
            json.dumps(rows),
            encoding="utf-8",
        )

    frame = module.build_market_regime_frame(raw)

    assert list(frame.columns) == list(REGIME_FEATURES)
    assert len(frame) >= 252
    assert frame.index.is_monotonic_increasing
    assert frame.index.is_unique
    assert np.isfinite(frame.to_numpy(dtype=float)).all()


def test_train_latest_regime_uses_configured_input_but_literal_output_root(
    tmp_path,
    monkeypatch,
):
    module = load_adaptive_regime()
    calls = {}
    configured_warehouse = tmp_path / "configured-warehouse"
    fixed_warehouse = tmp_path / "fixed-warehouse"

    def configured_path(*parts):
        return configured_warehouse.joinpath(*parts)

    def fake_build(path):
        calls["input"] = Path(path)
        return regime_frame()

    def fake_train(frame, *, feature_names, output_path, random_state):
        calls["rows"] = len(frame)
        calls["features"] = feature_names
        calls["output"] = Path(output_path)
        calls["random_state"] = random_state
        return {"artifact_sha256": "a" * 64}

    monkeypatch.setenv("QLIB_DATA_ROOT", str(configured_warehouse))
    monkeypatch.setattr(module, "resolve_data_path", configured_path)
    monkeypatch.setattr(module, "DEFAULT_DATA_ROOT", fixed_warehouse)
    monkeypatch.setattr(module, "build_market_regime_frame", fake_build)
    monkeypatch.setattr(module, "train_regime_model", fake_train)

    result = module.train_latest_regime()

    assert result["artifact_sha256"] == "a" * 64
    assert calls == {
        "input": (
            configured_warehouse
            / "datasets"
            / "a_share_6y_daily"
            / "raw"
        ),
        "rows": 360,
        "features": list(REGIME_FEATURES),
        "output": (
            fixed_warehouse
            / "models"
            / "regime"
            / "regime-latest.joblib"
        ),
        "random_state": 7,
    }
