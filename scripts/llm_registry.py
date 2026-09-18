"""Central LLM model catalog and effective-selection resolver.

The JSON catalog is the only place where provider/model ids are added or
removed. Runtime scene selection is kept here so UI, schedulers and research
tools do not invent their own fallback rules.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "config" / "llm_models.json"


@lru_cache(maxsize=1)
def _registry() -> dict[str, Any]:
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    providers = data.get("providers")
    if not isinstance(providers, dict) or not providers:
        raise ValueError("LLM registry must define providers")
    default_provider = str(data.get("default_provider") or "").strip().lower()
    if default_provider not in providers:
        raise ValueError("LLM registry default_provider is invalid")
    for provider, definition in providers.items():
        models = definition.get("models") if isinstance(definition, dict) else None
        ids = [str(item.get("id") or "").strip() for item in (models or []) if isinstance(item, dict)]
        if not ids or any(not model_id for model_id in ids):
            raise ValueError(f"LLM registry provider {provider} has no valid models")
        if str(definition.get("default_model") or "") not in ids:
            raise ValueError(f"LLM registry provider {provider} has invalid default_model")
    return data


def load_registry() -> dict[str, Any]:
    return copy.deepcopy(_registry())


def provider_ids() -> tuple[str, ...]:
    return tuple(_registry()["providers"].keys())


def normalize_provider(provider: object) -> str:
    value = str(provider or "").strip().lower()
    return value if value in _registry()["providers"] else str(_registry()["default_provider"])


def provider_definition(provider: object) -> dict[str, Any]:
    return copy.deepcopy(_registry()["providers"][normalize_provider(provider)])


def default_model(provider: object) -> str:
    return str(provider_definition(provider)["default_model"])


def normalize_model(provider: object, model: object = "") -> str:
    normalized_provider = normalize_provider(provider)
    definition = _registry()["providers"][normalized_provider]
    selected = str(model or definition["default_model"]).strip()
    selected = str((definition.get("aliases") or {}).get(selected, selected))
    supported = {str(item["id"]) for item in definition["models"]}
    return selected if selected in supported else str(definition["default_model"])


def is_registered_model(provider: object, model: object) -> bool:
    """Return true only for an exact provider/model pair in the catalog."""
    normalized_provider = str(provider or "").strip().lower()
    selected = str(model or "").strip()
    definition = _registry()["providers"].get(normalized_provider)
    if not isinstance(definition, dict) or not selected:
        return False
    selected = str((definition.get("aliases") or {}).get(selected, selected))
    return selected in {
        str(item["id"])
        for item in definition.get("models", [])
        if isinstance(item, dict) and item.get("id")
    }


def planner_fallbacks(provider: object, model: object) -> tuple[tuple[str, str], ...]:
    """Return deterministic model-pinned planner fallbacks.

    Models from the current provider come first, followed by other providers in
    catalog order. Callers still decide whether a retry is safe.
    """
    primary_provider = normalize_provider(provider)
    primary_model = normalize_model(primary_provider, model)
    providers = _registry()["providers"]
    ordered_providers = (primary_provider,) + tuple(
        item for item in providers if item != primary_provider
    )
    result: list[tuple[str, str]] = []
    for provider_id in ordered_providers:
        for item in providers[provider_id].get("models", []):
            model_id = str(item.get("id") or "").strip()
            if model_id and (provider_id, model_id) != (primary_provider, primary_model):
                result.append((provider_id, model_id))
    return tuple(result)


def public_catalog() -> dict[str, Any]:
    return load_registry()


def _global_selection(cache: Any) -> dict[str, Any]:
    settings = cache.get("llm:settings") if cache is not None else None
    if isinstance(settings, dict) and (settings.get("provider") or settings.get("model")):
        provider = normalize_provider(settings.get("provider"))
        return {
            "provider": provider,
            "model": normalize_model(provider, settings.get("model")),
            "source": "llm_settings",
        }
    provider = normalize_provider(None)
    return {"provider": provider, "model": default_model(provider), "source": "registry_default"}


def resolve_llm_selection(
    *,
    cache: Any = None,
    scene: str = "default",
    local_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve the effective provider/model for one runtime scene.

    Ordinary LLM settings are the global source. A research scene may opt out
    with ``inherit_global=false``; this resolver has no execution authority.
    """
    if cache is None:
        from quant.data.cache import create_cache

        cache = create_cache()
    selected = _global_selection(cache)
    local = local_config or {}
    if scene == "paper" and local.get("inherit_global") is False:
        provider = normalize_provider(local.get("provider"))
        selected = {
            "provider": provider,
            "model": normalize_model(provider, local.get("model")),
            "source": "paper_override",
        }
    return {
        **selected,
        "registry_version": int(_registry().get("schema_version") or 1),
    }
