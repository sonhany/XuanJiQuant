from pathlib import Path

import pytest

from quant.qlib.registry import Registry
from quant.qlib.workflow_bridge import WorkflowResult


REQUIRED = (
    "params.pkl",
    "pred.pkl",
    "label.pkl",
    "sig_analysis/ic.pkl",
    "sig_analysis/ric.pkl",
    "portfolio_analysis/report_normal_1day.pkl",
    "portfolio_analysis/positions_normal_1day.pkl",
    "portfolio_analysis/port_analysis_1day.pkl",
)


def fake_workflow_result(tmp_path, omit="", artifacts=None):
    root = tmp_path / "artifacts"
    for name in REQUIRED:
        if name == omit:
            continue
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("artifact:" + name).encode("utf-8"))
    return WorkflowResult(
        local_experiment_id="local_1",
        dataset_id="a_share_6y_daily",
        dataset_version="daily-pit-v1",
        quality_report_id="quality_1",
        handler="Alpha158",
        model_type="LightGBM",
        seed=42,
        qlib_experiment_id="experiment_1",
        recorder_id="recorder_1",
        status="succeeded",
        artifact_root=root,
        metrics={
            "Rank IC": 0.03,
            "Rank ICIR": 0.4,
            "Long-Short Ann Return": 0.12,
            "Long-Short Ann Sharpe": 1.2,
            "1day.excess_return_with_cost.annualized_return": 0.08,
            "1day.excess_return_with_cost.information_ratio": 1.1,
            "1day.excess_return_with_cost.max_drawdown": -0.09,
        },
        artifacts=list(REQUIRED) if artifacts is None else artifacts,
        config_hash="a" * 64,
    )


def test_import_rejects_missing_portfolio_record(tmp_path):
    from quant.qlib.artifact_importer import import_workflow_result

    result = fake_workflow_result(
        tmp_path,
        omit="portfolio_analysis/port_analysis_1day.pkl",
    )

    with pytest.raises(RuntimeError, match="port_analysis_1day"):
        import_workflow_result(result, Registry(tmp_path / "meta.db"))


def test_import_is_idempotent_and_hashes_files(tmp_path):
    from quant.qlib.artifact_importer import import_workflow_result

    result = fake_workflow_result(tmp_path)
    store = Registry(tmp_path / "meta.db")

    first = import_workflow_result(result, store)
    second = import_workflow_result(result, store)

    assert first["id"] == second["id"]
    assert len(store.list_workflow_runs()) == 1
    assert all(len(value) == 64 for value in first["artifacts"].values())
    assert first["metrics"]["rank_ic"] == pytest.approx(0.03)
    assert first["metrics"]["official_max_drawdown"] == pytest.approx(-0.09)
    assert store.get_experiment("local_1")["status"] == "succeeded"


def test_import_rejects_artifact_path_traversal(tmp_path):
    from quant.qlib.artifact_importer import import_workflow_result

    result = fake_workflow_result(tmp_path, artifacts=[*REQUIRED, "../escape.pkl"])

    with pytest.raises(RuntimeError, match="path traversal"):
        import_workflow_result(result, Registry(tmp_path / "meta.db"))


def test_import_rejects_non_succeeded_recorder_result(tmp_path):
    from dataclasses import replace

    from quant.qlib.artifact_importer import import_workflow_result

    result = replace(fake_workflow_result(tmp_path), status="failed")

    with pytest.raises(RuntimeError, match="not succeeded"):
        import_workflow_result(result, Registry(tmp_path / "meta.db"))
