import json


def test_shadow_signal_has_provenance_and_no_order_fields(tmp_path):
    from quant.qlib.shadow_signal import write_shadow_signal

    result = write_shadow_signal(
        output_dir=tmp_path,
        model_id="model_1",
        workflow_run_id="wf_1",
        dataset_version="daily-pit-v1",
        signal_hash="a" * 64,
        predictions=[
            {
                "date": "2026-08-03",
                "instrument": "SH600000",
                "score": 0.8,
                "rank": 1,
            }
        ],
    )
    payload = json.loads(result["path"].read_text(encoding="utf-8"))
    content = result["path"].read_text(encoding="utf-8")

    assert payload["schema_version"] == "xuanji_shadow_signal_v1"
    assert payload["workflow_run_id"] == "wf_1"
    assert payload["dataset_version"] == "daily-pit-v1"
    assert payload["signal_hash"] == "a" * 64
    assert payload["execution_authority"] is False
    assert payload["can_trigger_order"] is False
    assert result["path"].name == "2026-08-03.json"
    assert len(result["sha256"]) == 64
    for forbidden in ("quantity", "price", "order_type", "side", "orders"):
        assert forbidden not in content


def test_shadow_signal_rejects_multiple_trade_dates(tmp_path):
    import pytest

    from quant.qlib.shadow_signal import write_shadow_signal

    with pytest.raises(ValueError, match="one trade date"):
        write_shadow_signal(
            output_dir=tmp_path,
            model_id="model_1",
            workflow_run_id="wf_1",
            dataset_version="daily-pit-v1",
            signal_hash="a" * 64,
            predictions=[
                {"date": "2026-08-03", "instrument": "SH600000", "score": 0.8},
                {"date": "2026-08-04", "instrument": "SZ000001", "score": 0.7},
            ],
        )
