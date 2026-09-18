"""Active-project runtime wiring for F5; all legacy sources are read-only."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import fields
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from quant.data.cache import create_cache
from quant.data.sync_policy import load_sync_policy
from quant.risk.config import load_paper_execution_risk_config
from quant.research.publication import resolve_complete_artifact, resolve_complete_generation
from quant.strategy.f4_candidate_factory import FACTORY_VERSION_V2
from quant.strategy.f4_v2_publication import (
    resolve_committed_v2_candidate_evidence,
)

from .ledger import PaperLedger
from .policy import ExperimentalPaperPolicy, PaperExecutionPolicy
from .reporting import active_account_projection
from .service import PaperExecutionService


ROOT = Path(__file__).resolve().parents[2]
RESEARCH_PUBLICATION_ROOT = ROOT / "data" / "research" / "daily"
POLICY_PATH = ROOT / "config" / "f5_paper_execution.json"
F4_LATEST_PATH = ROOT / "data" / "research" / "f4" / "latest.json"
F4_VALIDATION_ROOT = ROOT / "data" / "research" / "f4"
EXPERIMENTAL_SELECTION_PATH = (
    ROOT / "data" / "research" / "experimental_selections" / "latest.json"
)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _completed_research_json(name: str, legacy_path: Path) -> dict[str, Any]:
    pointer_exists = (RESEARCH_PUBLICATION_ROOT / "latest.json").is_file()
    if pointer_exists:
        try:
            return _read_json(resolve_complete_artifact(RESEARCH_PUBLICATION_ROOT, name))
        except Exception:
            # F5 must not consume a compatibility mirror after an authoritative
            # pointer has failed its identity/hash check.
            return {}
    return _read_json(legacy_path)


def _selection_evidence() -> dict[str, Any]:
    return _completed_research_json(
        "selection.json",
        ROOT / "data" / "research" / "selections" / "latest.json",
    )


def _hydrate_committed_f4_projection(projection: dict[str, Any]) -> dict[str, Any]:
    """Hydrate a v2 projection only through the committed factory pointer."""

    if (
        projection.get("factory_version") != FACTORY_VERSION_V2
        and projection.get("candidate_spec_version") != FACTORY_VERSION_V2
    ):
        return projection
    factory_run_id = str(projection.get("factory_run_id") or "")
    if not factory_run_id:
        return {}
    try:
        resolved = resolve_committed_v2_candidate_evidence(
            ROOT, expected_factory_run_id=factory_run_id
        )
        candidate_spec = dict(resolved.get("candidate_spec") or {})
        models = resolved.get("model_artifacts")
        if (
            candidate_spec.get("version") != FACTORY_VERSION_V2
            or candidate_spec.get("factory_run_id") != factory_run_id
            or candidate_spec.get("promotion_state") != "research_only"
            or candidate_spec.get("execution_authority") is not False
            or not isinstance(models, list)
        ):
            return {}
        candidate_spec["model_artifacts"] = list(models)
        return {**projection, "candidate_spec": candidate_spec}
    except Exception:
        return {}


def _bound_committed_f4_evidence() -> dict[str, Any]:
    """Resolve the immutable F4 generation named by the current experimental selection."""

    selection = _read_json(EXPERIMENTAL_SELECTION_PATH)
    if selection.get("selection_status") != "experimental_research_portfolio":
        return {}
    validation_id = str(selection.get("f4_validation_id") or "")
    factory_run_id = str(selection.get("f4_factory_run_id") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", validation_id) or not re.fullmatch(
        r"[0-9a-f]{64}", factory_run_id
    ):
        return {}
    try:
        generation = resolve_complete_generation(RESEARCH_PUBLICATION_ROOT)
        generation_id = str(generation["pointer"].get("generation_id") or "")
    except Exception:
        return {}
    if not generation_id or str(selection.get("research_generation_id") or "") != generation_id:
        return {}
    validation_dir = (F4_VALIDATION_ROOT / validation_id).resolve()
    try:
        validation_dir.relative_to(F4_VALIDATION_ROOT.resolve())
    except ValueError:
        return {}
    report = _read_json(validation_dir / "validation_report.json")
    declared = report.get("artifact_hashes")
    if not isinstance(declared, dict) or not declared:
        return {}
    for name, expected_hash in declared.items():
        if Path(str(name)).name != str(name) or not re.fullmatch(
            r"[0-9a-f]{64}", str(expected_hash or "")
        ):
            return {}
        artifact = validation_dir / str(name)
        if not artifact.is_file() or _sha256(artifact) != expected_hash:
            return {}
    if (
        report.get("status") != "f4_rejected"
        or report.get("validation_id") != validation_id
        or report.get("factory_run_id") != factory_run_id
        or report.get("candidate_spec_version") != FACTORY_VERSION_V2
        or report.get("promotion_state") != "research_only"
        or report.get("execution_authority") is not False
    ):
        return {}
    try:
        selection_date = datetime.strptime(
            str(selection.get("selection_date") or "").replace("-", ""), "%Y%m%d"
        )
        validation_date = datetime.strptime(
            str(report.get("market_date") or "").replace("-", ""), "%Y%m%d"
        )
        maximum_age_days = load_sync_policy()["f4_strategy"].stale_after_ms / 86_400_000
    except (KeyError, TypeError, ValueError):
        return {}
    age_days = (selection_date - validation_date).days
    if age_days < 0 or age_days > maximum_age_days:
        return {}
    try:
        resolved = resolve_committed_v2_candidate_evidence(
            ROOT, expected_factory_run_id=factory_run_id
        )
        candidate_spec = dict(resolved.get("candidate_spec") or {})
        models = resolved.get("model_artifacts")
        if (
            candidate_spec.get("version") != FACTORY_VERSION_V2
            or candidate_spec.get("factory_run_id") != factory_run_id
            or candidate_spec.get("promotion_state") != "research_only"
            or candidate_spec.get("execution_authority") is not False
            or not isinstance(models, list)
        ):
            return {}
    except Exception:
        return {}
    candidate_spec["model_artifacts"] = list(models)
    return {
        **report,
        "factory_version": FACTORY_VERSION_V2,
        "candidate_spec": candidate_spec,
        "evidence_source": "selection_bound_committed_f4",
    }


def _f4_evidence() -> dict[str, Any]:
    projection = _read_json(F4_LATEST_PATH)
    hydrated = _hydrate_committed_f4_projection(projection)
    if hydrated:
        return hydrated
    return _bound_committed_f4_evidence()


def _research_bundle() -> dict[str, Any]:
    if not (RESEARCH_PUBLICATION_ROOT / "latest.json").is_file():
        return {
            "selection": _selection_evidence(),
            "factor": _factor_evidence(),
        }
    try:
        generation = resolve_complete_generation(RESEARCH_PUBLICATION_ROOT)
        paths = generation["paths"]
        projection = _read_json(paths["factor_snapshot_latest.json"])
        factor = {
            "snapshot_id": projection.get("snapshot_id"),
            "data_version": projection.get("data_version"),
            "as_of": projection.get("as_of") or projection.get("latest_kline_date"),
            "quality_passed": bool(
                projection.get("snapshot_id")
                and projection.get("data_version")
                and (projection.get("as_of") or projection.get("latest_kline_date"))
            ),
        }
        generation_id = str(generation["pointer"].get("generation_id") or "")
        f4_latest = _f4_evidence()
        if str(f4_latest.get("status") or "") == "f4_rejected":
            selection = _read_json(EXPERIMENTAL_SELECTION_PATH)
            if (
                selection.get("selection_status") != "experimental_research_portfolio"
                or str(selection.get("research_generation_id") or "") != generation_id
            ):
                selection = {}
        else:
            selection = _read_json(paths["selection.json"])
        return {
            "generation_id": generation_id,
            "selection": selection,
            "factor": factor,
        }
    except Exception:
        return {"selection": {}, "factor": {"quality_passed": False}}


def load_policy() -> PaperExecutionPolicy:
    raw = _read_json(POLICY_PATH)
    allowed = {item.name for item in fields(PaperExecutionPolicy)}
    values = {key: value for key, value in raw.items() if key in allowed}
    experimental_raw = values.pop("experimental_paper", {})
    if not isinstance(experimental_raw, dict):
        raise ValueError("experimental_policy_invalid")
    experimental_allowed = {item.name for item in fields(ExperimentalPaperPolicy)}
    experimental_values = {
        key: value for key, value in experimental_raw.items() if key in experimental_allowed
    }
    if "allowed_f4_statuses" in experimental_values:
        experimental_values["allowed_f4_statuses"] = tuple(
            experimental_values["allowed_f4_statuses"]
        )
    values["experimental_paper"] = ExperimentalPaperPolicy(**experimental_values)
    return PaperExecutionPolicy(**values)


def _read_quant_key(key: str) -> Any:
    path = ROOT / "data" / "quant.db"
    if not path.is_file():
        return None
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
    try:
        row = connection.execute("SELECT value, exp FROM kv WHERE key=?", (key,)).fetchone()
        if row is None:
            return None
        if row[1] is not None and float(row[1]) < datetime.now().timestamp():
            return None
        return json.loads(row[0])
    finally:
        connection.close()


def _factor_evidence() -> dict[str, Any]:
    value = _completed_research_json(
        "factor_snapshot_latest.json", ROOT / "data" / "factor_snapshot_latest.json"
    )
    return {
        "snapshot_id": value.get("snapshot_id"),
        "data_version": value.get("data_version"),
        "as_of": value.get("as_of") or value.get("latest_kline_date"),
        "quality_passed": bool(value.get("snapshot_id") and value.get("data_version") and value.get("as_of")),
    }


def _market_bar(code: str, session: str) -> dict[str, Any] | None:
    rows = _read_quant_key(f"kline:{str(code).zfill(6)}:d")
    for row in reversed(rows if isinstance(rows, list) else []):
        row_date = str(row.get("date") or row.get("d") or "").replace("-", "")
        if row_date == str(session).replace("-", ""):
            value = dict(row)
            value["date"] = row_date
            value["suspended"] = float(value.get("volume") or 0) <= 0
            change = float(value.get("change_pct") or value.get("pct_chg") or 0)
            value["limit_up"] = change >= 9.9
            value["limit_down"] = change <= -9.9
            return value
    return None


def _fetch_realtime_quotes(codes: list[str]) -> dict[str, dict[str, Any]]:
    from scripts.market_data import fetch_realtime

    vendor_codes = []
    for raw in codes:
        code = str(raw).zfill(6)
        prefix = "sh" if code.startswith("6") else "bj" if code.startswith(("4", "8", "9")) else "sz"
        vendor_codes.append(prefix + code)
    return dict(fetch_realtime(vendor_codes, use_cache=False) or {})


def _next_session(market_date: str) -> str:
    compact = str(market_date).replace("-", "")
    calendar = _read_quant_key("calendar:trade_dates")
    future = [str(value) for value in (calendar if isinstance(calendar, list) else []) if str(value) > compact]
    if future:
        return min(future)
    # The governed history cannot contain tomorrow before it trades.  Use the
    # project's exchange-calendar projection only to name a prepared session;
    # settlement still requires an actual governed bar for that date.
    cursor = datetime.strptime(compact, "%Y%m%d")
    while True:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            return cursor.strftime("%Y%m%d")


def build_runtime_service() -> PaperExecutionService:
    ledger_path = Path(os.environ.get("XUANJI_F5_LEDGER", ROOT / "data" / "paper" / "f5_ledger.db"))
    policy = load_policy()
    ledger = PaperLedger(ledger_path)
    if ledger.get_setting("enabled", None) is None:
        ledger.set_setting("enabled", policy.enabled)
    if ledger.get_setting("kill_switch", None) is None:
        ledger.set_setting("kill_switch", policy.kill_switch)
    return PaperExecutionService(
        ledger=ledger,
        policy=policy,
        risk=load_paper_execution_risk_config(),
        selection_loader=_selection_evidence,
        f4_loader=_f4_evidence,
        factor_loader=_factor_evidence,
        market_bar_loader=_market_bar,
        next_session=_next_session,
        research_bundle_loader=_research_bundle,
        realtime_quote_loader=_fetch_realtime_quotes,
    )


def load_active_account_projection(limit: int = 200) -> dict[str, Any]:
    """Read the unique active simulated account without legacy fallback."""
    service = build_runtime_service()
    cache = create_cache()
    active_codes = {
        str(row.get("code") or "").zfill(6)
        for row in service.ledger.list_positions()
        if isinstance(row, dict) and str(row.get("code") or "").strip()
    }
    names: dict[str, str] = {}
    for row in list((_selection_evidence().get("positions") or [])):
        if isinstance(row, dict):
            code = str(row.get("code") or "").zfill(6)
            name = str(row.get("name") or "").strip()
            if code and name:
                names[code] = name
    factor_names_loaded = False

    def resolve_name(code: str) -> str:
        nonlocal factor_names_loaded
        normalized = str(code).zfill(6)
        known = str(names.get(normalized) or cache.get(f"stock:name:{normalized}") or "").strip()
        if known:
            return known
        if not factor_names_loaded:
            for row in list((_factor_evidence().get("rows") or [])):
                if isinstance(row, dict):
                    factor_code = str(row.get("code") or "").zfill(6)
                    factor_name = str(row.get("name") or "").strip()
                    if factor_code and factor_name:
                        names.setdefault(factor_code, factor_name)
            factor_names_loaded = True
        return str(names.get(normalized) or "")
    try:
        return active_account_projection(
            service.ledger,
            service.policy.initial_capital,
            limit=limit,
            name_resolver=resolve_name,
        )
    finally:
        service.ledger.close()
        close_cache = getattr(cache, "close", None)
        if callable(close_cache):
            close_cache()
