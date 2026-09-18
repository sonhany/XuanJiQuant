from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd


DEFAULT_PARAMS = {
    "objective": "regression",
    "learning_rate": 0.03,
    "n_estimators": 500,
    "num_leaves": 31,
    "max_depth": -1,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "random_state": 42,
    "n_jobs": -1,
    "verbosity": -1,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_model(path: str | Path) -> lgb.Booster:
    return lgb.Booster(model_file=str(path))


def train_lightgbm(
    dataset: dict[str, Any],
    *,
    output_dir: Path,
    seed: int = 42,
    params: dict[str, Any] | None = None,
    experiment_id: str | None = None,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    experiment_id = experiment_id or f"lgbm_{uuid.uuid4().hex[:16]}"
    temp_dir = output_dir / f".{experiment_id}.tmp"
    artifact_dir = output_dir / experiment_id
    shutil.rmtree(temp_dir, ignore_errors=True)
    temp_dir.mkdir(parents=True)

    config = dict(DEFAULT_PARAMS)
    config.update(params or {})
    config["random_state"] = int(seed)
    feature_names = list(dataset.get("feature_names") or [])
    train_x = dataset["train_x"]
    valid_x = dataset["valid_x"]
    test_x = dataset["test_x"]
    if feature_names:
        if not isinstance(train_x, pd.DataFrame):
            train_x = pd.DataFrame(train_x, columns=feature_names)
        if not isinstance(valid_x, pd.DataFrame):
            valid_x = pd.DataFrame(valid_x, columns=feature_names)
        if not isinstance(test_x, pd.DataFrame):
            test_x = pd.DataFrame(test_x, columns=feature_names)
    model = lgb.LGBMRegressor(**config)
    model.fit(
        train_x,
        dataset["train_y"],
        eval_set=[(valid_x, dataset["valid_y"])],
        callbacks=[lgb.early_stopping(50, verbose=False)],
    )
    predictions = model.predict(test_x)
    model_path = temp_dir / "model.txt"
    model.booster_.save_model(str(model_path))

    restored = load_model(model_path)
    restored_predictions = restored.predict(test_x)
    if not np.allclose(predictions, restored_predictions, equal_nan=True):
        raise RuntimeError("saved LightGBM model failed round-trip verification")

    (temp_dir / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (temp_dir / "features.json").write_text(
        json.dumps(
            list(dataset.get("feature_names") or []),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    checksum = _sha256(model_path)
    (temp_dir / "sha256.txt").write_text(checksum + "\n", encoding="ascii")
    if artifact_dir.exists():
        raise FileExistsError(artifact_dir)
    temp_dir.replace(artifact_dir)
    final_model_path = artifact_dir / "model.txt"
    return {
        "experiment_id": experiment_id,
        "artifact_dir": artifact_dir,
        "model_path": str(final_model_path),
        "sha256": checksum,
        "best_iteration": int(model.best_iteration_ or config["n_estimators"]),
        "test_predictions": np.asarray(predictions),
    }
