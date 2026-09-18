import numpy as np


def test_model_round_trip_is_reproducible(tmp_path):
    from quant.qlib.trainer import load_model, train_lightgbm

    rng = np.random.default_rng(42)
    train_x = rng.normal(size=(300, 8))
    train_y = train_x[:, 0] * 0.2 - train_x[:, 1] * 0.1 + rng.normal(
        scale=0.05, size=300
    )
    valid_x = rng.normal(size=(80, 8))
    valid_y = valid_x[:, 0] * 0.2 - valid_x[:, 1] * 0.1
    test_x = rng.normal(size=(60, 8))
    dataset = {
        "train_x": train_x,
        "train_y": train_y,
        "valid_x": valid_x,
        "valid_y": valid_y,
        "test_x": test_x,
        "feature_names": [f"f{i}" for i in range(8)],
    }

    result = train_lightgbm(dataset, output_dir=tmp_path, seed=42)
    restored = load_model(result["model_path"])

    assert np.allclose(
        result["test_predictions"],
        restored.predict(test_x),
    )
    assert len(result["sha256"]) == 64
    assert result["artifact_dir"].exists()
