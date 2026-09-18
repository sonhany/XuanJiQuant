from quant.qlib.capabilities import build_capability_catalog


def test_code_presence_does_not_mean_ready():
    catalog = build_capability_catalog(
        environment={"ready": True, "versions": {"pyqlib": "0.9.7"}},
        quality_report=None,
        latest_workflow=None,
        dependencies={"xgboost": False},
    )
    by_id = {item["id"]: item["status"] for item in catalog}
    assert by_id["data"] == "受限"
    assert by_id["workflow"] == "未接入"
    assert by_id["xgboost"] == "受限"
    assert by_id["deep_learning"] == "未接入"


def test_workflow_ready_requires_complete_recorder():
    catalog = build_capability_catalog(
        environment={"ready": True, "versions": {"pyqlib": "0.9.7"}},
        quality_report={"passed": True},
        latest_workflow={"status": "succeeded", "artifacts_complete": True},
        dependencies={"xgboost": True},
    )
    by_id = {item["id"]: item["status"] for item in catalog}
    assert by_id["data"] == "可用"
    assert by_id["workflow"] == "可用"
    assert by_id["xgboost"] == "受限"


def test_model_capability_requires_its_own_complete_workflow_evidence():
    catalog = build_capability_catalog(
        environment={"ready": True},
        quality_report={"passed": True},
        latest_workflow={
            "status": "succeeded",
            "artifacts_complete": True,
            "available_handlers": ["Alpha158", "Alpha360"],
            "available_models": ["LightGBM", "XGBoost", "Linear"],
        },
        dependencies={"xgboost": True},
    )
    by_id = {item["id"]: item["status"] for item in catalog}
    assert by_id["alpha360"] == "可用"
    assert by_id["xgboost"] == "可用"
    assert by_id["linear"] == "可用"


def test_running_and_failed_states_are_truthful():
    running = build_capability_catalog(
        environment={"ready": True},
        quality_report={"passed": True},
        latest_workflow={"status": "running", "artifacts_complete": False},
        dependencies={"xgboost": True},
    )
    assert {item["id"]: item["status"] for item in running}["workflow"] == "运行中"

    failed = build_capability_catalog(
        environment={"ready": True},
        quality_report={"passed": False},
        latest_workflow={"status": "failed", "artifacts_complete": False},
        dependencies={"xgboost": True},
    )
    by_id = {item["id"]: item["status"] for item in failed}
    assert by_id["data"] == "失败"
    assert by_id["workflow"] == "失败"
