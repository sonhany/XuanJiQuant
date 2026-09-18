from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "collect_six_year_pit.py"
    spec = importlib.util.spec_from_file_location("collect_six_year_pit_contract", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_collection_lock_rejects_overlapping_writer(tmp_path):
    module = _load_script()
    path = tmp_path / ".collection.lock"
    with module.CollectionRunLock(path):
        with pytest.raises(RuntimeError, match="already running"):
            with module.CollectionRunLock(path):
                pass


def test_reference_must_be_source_healthy_and_nonempty(tmp_path):
    module = _load_script()
    target = tmp_path / "point_in_time" / "reference_data.json"
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps(
            {
                "current_universe": [{"instrument": "SH600000"}],
                "delistings": [],
                "source_health": {"passed": True},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="delisting ledger is empty"):
        module.load_reference(tmp_path)

