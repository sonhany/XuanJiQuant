from __future__ import annotations

import json

import pytest

from scripts.scan_strategies import (
    artifact_matches_input,
    load_governed_evaluation,
)


def _contract():
    return type(
        "Contract",
        (),
        {
            "snapshot_id": "daily-20260813",
            "data_version": "d" * 64,
            "universe_version": "u" * 64,
        },
    )()


def test_strategy_accepts_only_exact_factor_artifact_version():
    contract = _contract()
    assert artifact_matches_input(
        {
            "snapshot_id": contract.snapshot_id,
            "data_version": contract.data_version,
            "universe_version": contract.universe_version,
        },
        contract,
    ) is True
    assert artifact_matches_input(
        {
            "snapshot_id": "old",
            "data_version": contract.data_version,
            "universe_version": contract.universe_version,
        },
        contract,
    ) is False


def test_strategy_rejects_mismatched_ic_evaluation(tmp_path):
    evaluation = tmp_path / "factor_evaluation.json"
    evaluation.write_text(
        json.dumps(
            {
                "snapshot_id": "old",
                "data_version": "old",
                "universe_version": "old",
                "factors": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="factor evaluation input version mismatch"):
        load_governed_evaluation(evaluation, _contract())
