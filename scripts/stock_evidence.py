"""Stock-specific AI evidence review backed by deterministic valuation data."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from quant.valuation.contracts import normalize_code
from scripts.llm_registry import resolve_llm_selection


PROMPT_VERSION = "stock-evidence-v1"
CACHE_TTL = 30 * 60


def _bounded_snapshot(analysis: dict[str, Any]) -> dict[str, Any]:
    consensus = analysis.get("consensus") if isinstance(analysis.get("consensus"), dict) else {}
    valuations = analysis.get("valuations") if isinstance(analysis.get("valuations"), dict) else {}
    track_fields = ("status", "low", "mid", "high", "confidence", "error")
    compact_tracks = {}
    for name in ("absolute", "relative", "market"):
        track = valuations.get(name)
        if not isinstance(track, dict):
            continue
        compact_tracks[name] = {key: track.get(key) for key in track_fields}
        compact_tracks[name]["warnings"] = [str(item)[:160] for item in (track.get("warnings") or [])[:5]]
    return {
        "code": analysis.get("code"),
        "name": analysis.get("name"),
        "data_date": analysis.get("data_date"),
        "current_price": analysis.get("current_price"),
        "consensus": {
            key: consensus.get(key)
            for key in (
                "status", "base_low", "base_mid", "base_high",
                "final_low", "final_mid", "final_high",
                "market_adjustment", "data_quality",
            )
        },
        "valuations": compact_tracks,
        "data_quality": analysis.get("data_quality") or consensus.get("data_quality"),
        "financial_quality": analysis.get("financial_quality"),
    }


def analyze_stock_evidence(
    code: str,
    name: str = "",
    *,
    cache: Any = None,
    valuation_service: Any = None,
    chat_json_fn: Callable[..., dict] | None = None,
    selection: dict[str, Any] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    normalized = normalize_code(code)
    if not normalized:
        raise ValueError("invalid stock code")
    if cache is None:
        from quant.data.cache import create_cache

        cache = create_cache()
    if valuation_service is None:
        from quant.valuation.service import ValuationService

        valuation_service = ValuationService(cache=cache)
    if chat_json_fn is None:
        from scripts.llm_client import chat_json

        chat_json_fn = chat_json

    effective = selection or resolve_llm_selection(cache=cache, scene="stock_evidence")
    provider = effective["provider"]
    model = effective["model"]
    deterministic = valuation_service.analyze(normalized)
    snapshot = _bounded_snapshot(deterministic)
    snapshot["name"] = str(name or snapshot.get("name") or normalized)[:80]
    signature = str(deterministic.get("data_signature") or "")
    identity = hashlib.sha256(
        f"{normalized}|{signature}|{provider}|{model}|{PROMPT_VERSION}".encode("utf-8")
    ).hexdigest()[:32]
    cache_key = f"ai:stock_evidence:{normalized}:{identity}"
    if not force:
        cached = cache.get(cache_key)
        if isinstance(cached, dict) and cached.get("evidenceViews"):
            return {**cached, "cached": True}

    system = (
        "你是A股研究证据审阅员。只基于给定的确定性估值和数据质量快照形成证据摘要，"
        "不得补造新闻、财务数字或行情，不得生成交易指令。只返回合法JSON。"
    )
    user = (
        "请针对该股票返回JSON："
        '{"evidence_views":[{"title":"证据类别","focus":"核查重点","view":"证据结论"}],'
        '"overall":"综合研究结论","confidence":0.0,"risks":["主要风险"]}。'
        "至少覆盖估值、数据质量和风险三个视角；证据不足必须明确说明。\n"
        f"股票与证据快照：{json.dumps(snapshot, ensure_ascii=False, default=str, separators=(',', ':'))}"
    )
    result = chat_json_fn(
        provider,
        system,
        user,
        temperature=0.15,
        timeout=105,
        max_tokens=1800,
        max_retries=0,
        scene="stock_evidence",
        model=model,
    )
    if not isinstance(result, dict) or not result.get("success"):
        raise RuntimeError(str((result or {}).get("error") or "AI stock evidence failed")[:300])
    data = result.get("data") or {}
    raw_views = data.get("evidence_views") if isinstance(data, dict) else []
    evidence_views = []
    for item in raw_views if isinstance(raw_views, list) else []:
        if not isinstance(item, dict):
            continue
        evidence_views.append({
            "title": str(item.get("title") or "研究证据")[:60],
            "focus": str(item.get("focus") or "证据核查")[:80],
            "view": str(item.get("view") or "证据不足")[:600],
        })
        if len(evidence_views) >= 6:
            break
    if not evidence_views:
        evidence_views = [{"title": "研究证据", "focus": "返回校验", "view": "模型未返回有效证据条目"}]

    payload = {
        "code": normalized,
        "name": snapshot["name"],
        "provider": provider,
        "model": result.get("model") or model,
        "model_source": effective.get("source"),
        "registry_version": effective.get("registry_version"),
        "prompt_version": PROMPT_VERSION,
        "data_signature": signature,
        "evidenceViews": evidence_views,
        "overall": str(data.get("overall") or "证据不足，需人工复核")[:800],
        "confidence": data.get("confidence"),
        "risks": [str(item)[:160] for item in (data.get("risks") or [])[:10]],
        "usage": result.get("usage") or {},
        "safety_boundary": "research_only_no_order_action",
        "cache_key": cache_key,
    }
    cache.set(cache_key, payload, ttl=CACHE_TTL)
    cache.set("ai:stock_evidence:latest", payload)
    try:
        from quant.data.audit import write_audit_event

        write_audit_event(cache, "ai_stock_evidence", payload, source="market_data", ref_id=normalized)
    except Exception:
        pass
    return payload
