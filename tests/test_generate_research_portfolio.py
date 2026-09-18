import hashlib
import json
from pathlib import Path

import scripts.generate_research_portfolio as generator
from quant.strategy.f4_candidate_factory import (
    FACTORY_VERSION_V2,
    canonical_payload_hash,
)
from scripts.generate_research_portfolio import generate_once


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _prepare(root: Path) -> None:
    _write(
        root / "data" / "factor_snapshot_latest.json",
        {
            "as_of": "20260818",
            "latest_kline_date": "20260818",
            "snapshot_id": "daily-20260818",
            "data_version": "data-v1",
            "active_count": 2,
            "data_count": 2,
            "eligible_count": 2,
            "data_coverage": 1.0,
            "excluded_reasons": {},
            "promotion_state": "research_only",
            "execution_authority": False,
            "rows": [
                {
                    "code": "000001",
                    "name": "股票一",
                    "date": "20260818",
                    "close": 10.0,
                    "factors": {"range_pct": 1.0},
                },
                {
                    "code": "000002",
                    "name": "股票二",
                    "date": "20260818",
                    "close": 11.0,
                    "factors": {"range_pct": 2.0},
                },
            ],
        },
    )
    _write(
        root / "data" / "factor_evaluation.json",
        {
            "data_end_date": "20260818",
            "snapshot_id": "daily-20260818",
            "data_version": "data-v1",
            "factors": [{"factor": "range_pct"}],
            "promotion_state": "research_only",
            "execution_authority": False,
        },
    )
    _write(
        root / "data" / "research" / "f4" / "latest.json",
        {
            "validation_id": "f4-v1",
            "status": "f4_rejected",
            "promotion_state": "research_only",
            "execution_authority": False,
        },
    )
    _write(
        root / "data" / "research" / "f4" / "f4-v1" / "candidate_spec.json",
        {
            "validation_id": "f4-v1",
            "promotion_state": "research_only",
            "execution_authority": False,
            "factor_fits": [
                {
                    "window_id": "wf-01",
                    "fit_end": "2026-06-01",
                    "factors": ["range_pct"],
                    "directions": {"range_pct": -1},
                    "weights": {"range_pct": 1.0},
                }
            ],
        },
    )
    _write(
        root / "data" / "research" / "industry" / "pit_industry.json",
        {
            "records": [
                {
                    "instrument": "SZ000001",
                    "effective_from": "2020-01-01",
                    "industry_code": "I1",
                    "industry_name": "行业一",
                },
                {
                    "instrument": "SZ000002",
                    "effective_from": "2020-01-01",
                    "industry_code": "I2",
                    "industry_name": "行业二",
                },
            ]
        },
    )


def test_generate_once_writes_versioned_and_latest_identically(tmp_path):
    _prepare(tmp_path)

    first = generate_once(
        root=tmp_path,
        generated_at="2026-08-19T17:00:00+08:00",
    )
    second = generate_once(
        root=tmp_path,
        generated_at="2026-08-19T17:05:00+08:00",
    )

    versioned = (
        tmp_path
        / "data"
        / "research"
        / "selections"
        / first["portfolio_id"]
        / "portfolio.json"
    )
    latest = tmp_path / "data" / "research" / "selections" / "latest.json"
    assert first["portfolio_id"] == second["portfolio_id"]
    assert versioned.is_file()
    assert latest.is_file()
    assert json.loads(versioned.read_text(encoding="utf-8"))["portfolio_id"] == first[
        "portfolio_id"
    ]
    assert json.loads(latest.read_text(encoding="utf-8"))["portfolio_id"] == first[
        "portfolio_id"
    ]
    assert second["execution_authority"] is False


def test_generate_once_reads_staging_inputs_and_only_writes_staging_selection(
    tmp_path,
):
    _prepare(tmp_path)
    generation = tmp_path / "data" / "research" / "daily" / "generations" / "g1.staging"
    generation.mkdir(parents=True)
    factor_snapshot = generation / "factor_snapshot_latest.json"
    factor_evaluation = generation / "factor_evaluation.json"
    factor_snapshot.write_bytes(
        (tmp_path / "data" / "factor_snapshot_latest.json").read_bytes()
    )
    factor_evaluation.write_bytes(
        (tmp_path / "data" / "factor_evaluation.json").read_bytes()
    )
    (tmp_path / "data" / "factor_snapshot_latest.json").unlink()
    (tmp_path / "data" / "factor_evaluation.json").unlink()
    selection_output = generation / "selection.json"

    result = generate_once(
        root=tmp_path,
        generated_at="2026-08-19T17:00:00+08:00",
        factor_snapshot_path=factor_snapshot,
        factor_evaluation_path=factor_evaluation,
        selection_output_path=selection_output,
    )

    assert json.loads(selection_output.read_text(encoding="utf-8"))["portfolio_id"] == result[
        "portfolio_id"
    ]
    assert (
        tmp_path / "data" / "research" / "selections" / "latest.json"
    ).exists() is False


def test_generate_once_resolves_v2_winner_from_authoritative_generation(
    tmp_path, monkeypatch
):
    _prepare(tmp_path)
    factory_run_id = "f" * 64
    validation_id = "v" * 64
    policy = {
        "top_k": 10,
        "rebalance_bars": 10,
        "max_name_weight": 0.095,
        "max_industry_weight": 0.25,
        "lot_size": 100,
        "adv_participation": 0.10,
        "target_gross_exposure": 0.95,
        "version": "f4-standard-top10-policy-v2",
    }
    policy_hash = canonical_payload_hash(policy)
    lock_core = {
        "factory_run_id": factory_run_id,
        "window_id": "wf-01",
        "candidate_id": "candidate-v2",
        "alpha_spec_hash": "a" * 64,
        "alpha_fit_hash": "b" * 64,
        "model_artifact_hash": None,
        "portfolio_policy_hash": policy_hash,
    }
    lock_hash = canonical_payload_hash(lock_core)
    fit_path = tmp_path / "locked" / "alpha-fit.json"
    fit = {
        "window_id": "wf-01",
        "candidate_id": "candidate-v2",
        "artifact_hash": "b" * 64,
        "fit_end": "2026-06-01",
        "selected_signals": ["range_pct"],
        "directions": {"range_pct": -1},
        "weights": {"range_pct": 1.0},
        "median_rank_ic": {"range_pct": -0.1},
        "direction_consistency": {"range_pct": 0.7},
    }
    _write(fit_path, fit)
    candidate_spec = {
        "version": FACTORY_VERSION_V2,
        "factory_run_id": factory_run_id,
        "promotion_state": "research_only",
        "execution_authority": False,
        "factor_fits": [
            {
                "window_id": "wf-01",
                "candidate_id": "candidate-v2",
                "alpha_spec_hash": "a" * 64,
                "alpha_fit_hash": "b" * 64,
                "alpha_fit_artifact_hash": hashlib.sha256(
                    fit_path.read_bytes()
                ).hexdigest(),
                "alpha_fit_path": str(fit_path),
            }
        ],
        "selection_locks": [
            {
                **lock_core,
                "lock_hash": lock_hash,
                "promotion_state": "research_only",
                "execution_authority": False,
            }
        ],
        "selected_policies": [
            {
                "window_id": "wf-01",
                "candidate_id": "candidate-v2",
                **policy,
                "lock_hash": lock_hash,
                "policy_hash": policy_hash,
            }
        ],
    }
    generation = tmp_path / "factory-v2" / factory_run_id
    _write(
        generation / "model_artifacts.json",
        {
            "factory_run_id": factory_run_id,
            "models": [],
            "promotion_state": "research_only",
            "execution_authority": False,
        },
    )
    _write(
        tmp_path / "data" / "research" / "f4" / "latest.json",
        {
            "validation_id": validation_id,
            "factory_run_id": factory_run_id,
            "factory_version": FACTORY_VERSION_V2,
            "candidate_spec_version": FACTORY_VERSION_V2,
            "status": "f4_rejected",
            "promotion_state": "research_only",
            "execution_authority": False,
        },
    )
    calls = []
    monkeypatch.setattr(
        generator,
        "resolve_committed_v2_generation",
        lambda root, expected_factory_run_id: calls.append(
            (Path(root), expected_factory_run_id)
        )
        or {
            "factory_run_id": factory_run_id,
            "factory_version": FACTORY_VERSION_V2,
            "generation_dir": str(generation),
            "factory_report": {
                "factory_run_id": factory_run_id,
                "factory_version": FACTORY_VERSION_V2,
                "promotion_state": "research_only",
                "execution_authority": False,
                "pipeline_result": {"candidate_spec": candidate_spec},
            },
        },
        raising=False,
    )
    output = tmp_path / "selection-v2.json"

    result = generate_once(
        root=tmp_path,
        generated_at="2026-08-19T17:00:00+08:00",
        selection_output_path=output,
    )

    assert calls == [(tmp_path.resolve(), factory_run_id)]
    assert result["f4_factory_version"] == FACTORY_VERSION_V2
    assert result["f4_validation_id"] == validation_id
    assert result["factor_fit_factors"] == ["range_pct"]
    assert output.is_file()
def test_blocked_latest_f4_uses_prior_experimental_selection_bound_validation(tmp_path):
    from scripts import generate_research_portfolio as generator

    validation_id = "c" * 64
    factory_run_id = "f" * 64
    latest = {
        "status": "f4_blocked",
        "reason_code": "f3_pit_date_mismatch",
        "candidate_spec_version": "f4-multi-alpha-candidate-factory-v2",
        "promotion_state": "research_only",
        "execution_authority": False,
    }
    experimental = tmp_path / "data" / "research" / "experimental_selections" / "latest.json"
    experimental.parent.mkdir(parents=True)
    experimental.write_text(
        json.dumps({
            "selection_status": "experimental_research_portfolio",
            "selection_date": "20260904",
            "f4_validation_id": validation_id,
            "f4_factory_run_id": factory_run_id,
            "promotion_state": "research_only",
            "execution_authority": False,
        }),
        encoding="utf-8",
    )
    validation = tmp_path / "data" / "research" / "f4" / validation_id / "validation_report.json"
    validation.parent.mkdir(parents=True)
    validation.write_text(
        json.dumps({
            "status": "f4_rejected",
            "validation_id": validation_id,
            "factory_run_id": factory_run_id,
            "factory_version": "f4-multi-alpha-candidate-factory-v2",
            "candidate_spec_version": "f4-multi-alpha-candidate-factory-v2",
            "market_date": "2026-08-31",
            "promotion_state": "research_only",
            "execution_authority": False,
        }),
        encoding="utf-8",
    )

    result = generator._load_reusable_f4_evidence(
        tmp_path, latest, target_date="20260908"
    )

    assert result["status"] == "f4_rejected"
    assert result["validation_id"] == validation_id
    assert result["factory_run_id"] == factory_run_id
