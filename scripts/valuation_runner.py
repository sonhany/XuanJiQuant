"""Persistent JSON-lines runner for stock valuation research."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quant.valuation.contracts import normalize_code
from quant.valuation.service import ValuationService


_SERVICE: ValuationService | None = None


def service() -> ValuationService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = ValuationService()
    return _SERVICE


def ok(data: dict[str, Any]) -> dict[str, Any]:
    return {"success": True, "data": data}


def fail(error: str, *, status: int = 500) -> dict[str, Any]:
    return {"success": False, "status": status, "error": str(error)[:500]}


def _code(req: dict[str, Any]) -> str:
    code = normalize_code(req.get("code"))
    if not code:
        raise ValueError("invalid code")
    return code


def action_analyze(req: dict[str, Any]) -> dict[str, Any]:
    return ok(service().analyze(_code(req), force=bool(req.get("force"))))


def action_glm_analyze(req: dict[str, Any]) -> dict[str, Any]:
    from scripts.llm_registry import resolve_llm_selection

    effective = resolve_llm_selection(scene="valuation")
    return ok(service().glm_analyze(
        _code(req),
        force=bool(req.get("force")),
        provider=effective["provider"],
        model=effective["model"],
        model_source=effective["source"],
    ))


def action_latest(req: dict[str, Any]) -> dict[str, Any]:
    return ok(service().latest(_code(req)))


ACTIONS = {
    "analyze": action_analyze,
    "glm_analyze": action_glm_analyze,
    "latest": action_latest,
}


def handle(req: dict[str, Any]) -> dict[str, Any]:
    action = str(req.get("action") or "latest")
    handler = ACTIONS.get(action)
    if handler is None:
        return fail(f"unsupported action: {action}", status=400)
    try:
        return handler(req)
    except ValueError as exc:
        return fail(str(exc), status=400)
    except Exception as exc:
        return fail(f"valuation service failed: {str(exc)}", status=500)


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        req_id = None
        try:
            req = json.loads(line)
            if not isinstance(req, dict):
                raise ValueError("request must be a JSON object")
            req_id = req.pop("__id", None)
            response = handle(req)
        except (ValueError, json.JSONDecodeError) as exc:
            response = fail(str(exc), status=400)
        except Exception as exc:
            response = fail(f"runner failed: {str(exc)}", status=500)
        if req_id is not None:
            response["__id"] = req_id
        print(
            json.dumps(response, ensure_ascii=False, separators=(",", ":")),
            flush=True,
        )


if __name__ == "__main__":
    main()
