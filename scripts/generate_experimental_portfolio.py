"""Publish a version-bound experimental research portfolio for F5 simulation."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from quant.research.publication import resolve_complete_generation
from quant.strategy.experimental_selection import (
    build_experimental_selection,
    build_experimental_selection_from_research,
)
from quant.strategy.research_selection import ResearchSelectionBlocked
from scripts.generate_research_portfolio import (
    _load_candidate_spec,
    _load_reusable_f4_evidence,
)


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        with suppress(OSError):
            temporary.unlink()


def generate_once(
    *,
    root: str | Path = PROJECT_ROOT,
    generated_at: str | None = None,
    expected_generation_id: str | None = None,
) -> dict[str, Any]:
    project_root = Path(root).resolve()
    generation = resolve_complete_generation(
        project_root / "data" / "research" / "daily"
    )
    generation_id = str(generation.get("pointer", {}).get("generation_id") or "")
    if not generation_id:
        raise RuntimeError("research_generation_identity_missing")
    if expected_generation_id and generation_id != str(expected_generation_id):
        raise RuntimeError("research_generation_identity_mismatch")
    paths = dict(generation.get("paths") or {})
    research_selection = _read_object(Path(paths["selection.json"]))
    f4_latest = _load_reusable_f4_evidence(
        project_root,
        _read_object(project_root / "data" / "research" / "f4" / "latest.json"),
        target_date=str(research_selection.get("selection_date") or ""),
    )
    if f4_latest.get("status") == "f4_research_candidate":
        return {
            "success": True,
            "status": "not_applicable",
            "reason_code": "f4_already_validated",
            "research_generation_id": generation_id,
            "promotion_state": "research_only",
            "execution_authority": False,
        }
    timestamp = generated_at or datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(
        timespec="seconds"
    )
    try:
        candidate = build_experimental_selection_from_research(
            research_selection=research_selection,
            f4_latest=f4_latest,
            research_generation_id=generation_id,
            generated_at=timestamp,
        )
    except ResearchSelectionBlocked as exc:
        if exc.reason_code not in {
            "experimental_research_selection_invalid",
            "experimental_factory_identity_mismatch",
        }:
            raise
        factor_snapshot = _read_object(Path(paths["factor_snapshot_latest.json"]))
        factor_evaluation = _read_object(Path(paths["factor_evaluation.json"]))
        candidate_spec = _load_candidate_spec(project_root, f4_latest)
        industry = _read_object(
            project_root / "data" / "research" / "industry" / "pit_industry.json"
        )
        candidate = build_experimental_selection(
            factor_snapshot=factor_snapshot,
            factor_evaluation=factor_evaluation,
            f4_latest=f4_latest,
            candidate_spec=candidate_spec,
            industry_records=industry.get("records") or [],
            research_generation_id=generation_id,
            generated_at=timestamp,
        )
    selection_root = (
        project_root / "data" / "research" / "experimental_selections"
    )
    versioned = selection_root / candidate["portfolio_id"] / "portfolio.json"
    if versioned.is_file():
        payload = _read_object(versioned)
        if payload.get("portfolio_id") != candidate["portfolio_id"]:
            raise RuntimeError("experimental_selection_identity_collision")
    else:
        payload = candidate
        _atomic_json(versioned, payload)
    _atomic_json(selection_root / "latest.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="生成F5实验模拟研究组合")
    parser.add_argument("--generation-id", default="")
    args = parser.parse_args()
    try:
        result = generate_once(
            expected_generation_id=str(args.generation_id or "") or None
        )
        print(
            json.dumps(
                {
                    "success": True,
                    "status": result.get("status") or "generated",
                    "portfolio_id": result.get("portfolio_id"),
                    "position_count": result.get("position_count", 0),
                    "research_generation_id": result.get("research_generation_id"),
                    "promotion_state": "research_only",
                    "execution_authority": False,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "reason_code": str(exc).split(":", 1)[0]
                    or "experimental_selection_failed",
                    "error": str(exc),
                    "execution_authority": False,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
