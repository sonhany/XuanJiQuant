from quant.data.audit import (
    get_audit_replay,
    write_audit_event,
    write_model_call,
    write_order_event,
)
from quant.data.cache import SqliteCache


def test_audit_replay_requires_all_identifiers_and_links_model_calls(tmp_path):
    cache = SqliteCache(str(tmp_path / "audit.db"))
    write_audit_event(cache, "paper_run", {"run_id": "run-a", "decision_id": "decision-a"})
    write_order_event(cache, {
        "run_id": "run-a",
        "decision_id": "decision-a",
        "order_id": "order-a",
        "code": "600519",
        "direction": "buy",
        "quantity": 100,
        "status": "filled",
    })
    write_order_event(cache, {
        "run_id": "run-a",
        "decision_id": "decision-b",
        "order_id": "wrong-decision",
        "code": "000001",
        "direction": "buy",
        "quantity": 100,
        "status": "filled",
    })
    write_order_event(cache, {
        "run_id": "run-b",
        "decision_id": "decision-a",
        "order_id": "wrong-run",
        "code": "300750",
        "direction": "buy",
        "quantity": 100,
        "status": "filled",
    })
    write_model_call(cache, {
        "run_id": "run-a",
        "decision_id": "decision-a",
        "provider": "glm",
        "scene": "committee",
        "model": "unit",
        "success": True,
    })
    write_model_call(cache, {
        "run_id": "run-b",
        "decision_id": "decision-b",
        "provider": "glm",
        "scene": "other",
        "model": "unit",
        "success": True,
    })

    replay = get_audit_replay(cache, run_id="run-a", decision_id="decision-a")

    assert [row["order_id"] for row in replay["orders"]] == ["order-a"]
    assert [row["scene"] for row in replay["model_calls"]] == ["committee"]
