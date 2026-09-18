import json

import pytest

from scripts import generate_experimental_portfolio as generator
from tests.test_experimental_research_selection import (
    _candidate_spec,
    _f4,
    _factor_evaluation,
    _factor_snapshot,
    _industries,
)
from quant.strategy.research_selection import build_research_selection


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _project(tmp_path):
    generation = tmp_path / "data" / "research" / "daily" / "generations" / "generation-v1"
    snapshot = _write(generation / "factor_snapshot_latest.json", _factor_snapshot())
    evaluation = _write(generation / "factor_evaluation.json", _factor_evaluation())
    f4 = _write(tmp_path / "data" / "research" / "f4" / "latest.json", _f4())
    spec = _write(
        tmp_path / "data" / "research" / "f4" / "f4-v1" / "candidate_spec.json",
        _candidate_spec(),
    )
    industry = _write(
        tmp_path / "data" / "research" / "industry" / "pit_industry.json",
        {"records": _industries()},
    )
    selection = _write(
        generation / "selection.json",
        build_research_selection(
            factor_snapshot=_factor_snapshot(),
            factor_evaluation=_factor_evaluation(),
            f4_latest=_f4(),
            candidate_spec=_candidate_spec(),
            industry_records=_industries(),
            generated_at="2026-08-20T16:20:00+08:00",
        ),
    )
    return {
        "pointer": {"generation_id": "generation-v1"},
        "paths": {
            "factor_snapshot_latest.json": snapshot,
            "factor_evaluation.json": evaluation,
            "selection.json": selection,
        },
        "f4": f4,
        "spec": spec,
        "industry": industry,
    }


def test_generate_once_consumes_complete_generation_selection_without_rebuilding(
    tmp_path, monkeypatch
):
    generation = _project(tmp_path)
    generation["spec"].unlink()
    generation["industry"].unlink()
    monkeypatch.setattr(
        generator,
        "resolve_complete_generation",
        lambda _root: {
            "pointer": generation["pointer"],
            "paths": generation["paths"],
        },
    )

    result = generator.generate_once(
        root=tmp_path,
        generated_at="2026-08-20T16:20:00+08:00",
        expected_generation_id="generation-v1",
    )

    assert result["selection_status"] == "experimental_research_portfolio"
    assert result["research_generation_id"] == "generation-v1"


def test_generate_once_publishes_versioned_and_latest_experimental_selection(tmp_path, monkeypatch):
    generation = _project(tmp_path)
    monkeypatch.setattr(
        generator,
        "resolve_complete_generation",
        lambda _root: {"pointer": generation["pointer"], "paths": generation["paths"]},
    )

    result = generator.generate_once(
        root=tmp_path,
        generated_at="2026-08-20T16:20:00+08:00",
        expected_generation_id="generation-v1",
    )

    latest = tmp_path / "data" / "research" / "experimental_selections" / "latest.json"
    versioned = latest.parent / result["portfolio_id"] / "portfolio.json"
    assert latest.is_file()
    assert versioned.is_file()
    assert json.loads(latest.read_text(encoding="utf-8"))["portfolio_id"] == result["portfolio_id"]
    assert result["research_generation_id"] == "generation-v1"


def test_generate_once_is_idempotent_and_rejects_wrong_generation(tmp_path, monkeypatch):
    generation = _project(tmp_path)
    monkeypatch.setattr(
        generator,
        "resolve_complete_generation",
        lambda _root: {"pointer": generation["pointer"], "paths": generation["paths"]},
    )
    first = generator.generate_once(
        root=tmp_path,
        generated_at="2026-08-20T16:20:00+08:00",
        expected_generation_id="generation-v1",
    )
    second = generator.generate_once(
        root=tmp_path,
        generated_at="2026-08-20T16:25:00+08:00",
        expected_generation_id="generation-v1",
    )

    assert first["portfolio_id"] == second["portfolio_id"]
    with pytest.raises(RuntimeError, match="research_generation_identity_mismatch"):
        generator.generate_once(root=tmp_path, expected_generation_id="other")


def test_generate_once_rebuilds_experimental_selection_after_f4_identity_changes(
    tmp_path, monkeypatch
):
    generation = _project(tmp_path)
    old_selection = json.loads(
        generation["paths"]["selection.json"].read_text(encoding="utf-8")
    )
    old_selection["f4_validation_id"] = "old-validation"
    old_selection["f4_factory_run_id"] = "old-factory"
    generation["paths"]["selection.json"].write_text(
        json.dumps(old_selection, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(
        generator,
        "resolve_complete_generation",
        lambda _root: {"pointer": generation["pointer"], "paths": generation["paths"]},
    )

    result = generator.generate_once(
        root=tmp_path,
        generated_at="2026-08-20T22:00:00+08:00",
        expected_generation_id="generation-v1",
    )

    assert result["selection_status"] == "experimental_research_portfolio"
    assert result["f4_validation_id"] == _f4()["validation_id"]
    assert result["research_generation_id"] == "generation-v1"


def test_generate_once_reuses_selection_bound_f4_when_latest_retry_is_blocked(
    tmp_path, monkeypatch
):
    generation = _project(tmp_path)
    blocked = _f4(
        status="f4_blocked",
        reason_code="f3_pit_date_mismatch",
        reasons=["f3_pit_date_mismatch"],
    )
    generation["f4"].write_text(
        json.dumps(blocked, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(
        generator,
        "resolve_complete_generation",
        lambda _root: {"pointer": generation["pointer"], "paths": generation["paths"]},
    )
    reusable_calls = []
    monkeypatch.setattr(
        generator,
        "_load_reusable_f4_evidence",
        lambda project_root, latest, *, target_date: reusable_calls.append(
            (project_root, latest["status"], target_date)
        )
        or _f4(),
        raising=False,
    )

    result = generator.generate_once(
        root=tmp_path,
        generated_at="2026-08-20T22:10:00+08:00",
        expected_generation_id="generation-v1",
    )

    assert reusable_calls == [(tmp_path.resolve(), "f4_blocked", "20260818")]
    assert result["selection_status"] == "experimental_research_portfolio"
    assert result["f4_validation_id"] == "f4-v1"
    assert result["research_generation_id"] == "generation-v1"
