import json
from pathlib import Path

from scripts import jin10_runner


ROOT = Path(__file__).resolve().parents[1]


class FakeCache:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, *args, **kwargs):
        self.values[key] = value


def test_registry_is_the_single_model_catalog():
    from scripts.llm_registry import load_registry, normalize_model, planner_fallbacks

    registry = load_registry()

    assert registry["default_provider"] == "glm"
    assert [item["id"] for item in registry["providers"]["opencode"]["models"]] == [
        "deepseek-v4-flash-free",
        "nemotron-3-ultra-free",
    ]
    assert normalize_model("opencode", "deepseek") == "deepseek-v4-flash-free"
    assert normalize_model("opencode", "removed-model") == "deepseek-v4-flash-free"
    assert planner_fallbacks("glm", "glm-5.2") == (
        ("opencode", "deepseek-v4-flash-free"),
        ("opencode", "nemotron-3-ultra-free"),
    )
    assert planner_fallbacks("opencode", "deepseek-v4-flash-free")[0] == (
        "opencode",
        "nemotron-3-ultra-free",
    )


def test_llm_json_parser_keeps_outer_object_for_nested_plain_json():
    from scripts.llm_client import _extract_json

    parsed = _extract_json(
        '分析完成\n{"target_low":10,"target_mid":12,"target_high":14,'
        '"details":{"source":"rules","quality":{"status":"partial"}}}'
    )

    assert parsed["target_low"] == 10
    assert parsed["details"]["quality"]["status"] == "partial"


def test_scene_resolution_uses_global_model_and_allows_paper_override():
    from scripts.llm_registry import resolve_llm_selection

    cache = FakeCache({
        "llm:settings": {
            "provider": "opencode",
            "model": "nemotron-3-ultra-free",
        },
    })

    valuation = resolve_llm_selection(cache=cache, scene="valuation")
    inherited = resolve_llm_selection(
        cache=cache,
        scene="paper",
        local_config={"inherit_global": True, "provider": "glm", "model": "glm-5.2"},
    )
    overridden = resolve_llm_selection(
        cache=cache,
        scene="paper",
        local_config={"inherit_global": False, "provider": "glm", "model": "glm-5.2"},
    )

    assert valuation == {
        "provider": "opencode",
        "model": "nemotron-3-ultra-free",
        "source": "llm_settings",
        "registry_version": 1,
    }
    assert inherited["provider"] == "opencode"
    assert inherited["model"] == "nemotron-3-ultra-free"
    assert inherited["source"] == "llm_settings"
    assert overridden["provider"] == "glm"
    assert overridden["model"] == "glm-5.2"
    assert overridden["source"] == "paper_override"


def test_valuation_passes_effective_provider_and_model_to_client():
    from quant.valuation.glm import PROMPT_VERSION, glm_valuation

    captured = {}

    def fake_chat_json(provider, system, user, **kwargs):
        captured["provider"] = provider
        captured.update(kwargs)
        return {
            "success": True,
            "data": {
                "target_low": 10,
                "target_mid": 12,
                "target_high": 14,
                "confidence": 0.7,
                "assumptions": ["规则共识先合并绝对与相对估值，市场状态随后仅调整一次"],
                "drivers": ["盈利"],
                "risks": ["波动"],
                "invalidation_conditions": ["盈利失速"],
                "model_version": "nemotron-3-ultra-free",
                "prompt_version": PROMPT_VERSION,
            },
            "model": "nemotron-3-ultra-free",
            "usage": {},
        }

    _result, meta = glm_valuation(
        {"code": "300450"},
        current_price=11,
        chat_json_fn=fake_chat_json,
        provider="opencode",
        model="nemotron-3-ultra-free",
    )

    assert captured["provider"] == "opencode"
    assert captured["model"] == "nemotron-3-ultra-free"
    assert meta["provider"] == "opencode"
    assert meta["model"] == "nemotron-3-ultra-free"


def test_jin10_interpretation_cache_isolated_by_effective_model(monkeypatch):
    cache = FakeCache()
    calls = []
    monkeypatch.setattr(jin10_runner, "_cache", lambda: cache)

    from scripts import llm_client, llm_registry

    monkeypatch.setattr(
        llm_registry,
        "resolve_llm_selection",
        lambda **kwargs: {
            "provider": "opencode",
            "model": "nemotron-3-ultra-free",
            "source": "llm_settings",
            "registry_version": 1,
        },
    )
    monkeypatch.setattr(
        llm_client,
        "chat_json",
        lambda provider, system, user, **kwargs: calls.append((provider, kwargs.get("model"))) or {
            "success": True,
            "data": {
                "summary": "测试摘要",
                "market_impact": "neutral",
                "risk_level": "low",
                "related_assets": [],
                "related_sectors": [],
                "action_hint": "watch_only",
                "reason_codes": ["other"],
                "rationale": "测试",
            },
            "usage": {},
            "model": "nemotron-3-ultra-free",
        },
    )
    monkeypatch.setattr("quant.data.audit.write_audit_event", lambda *args, **kwargs: None)

    response = jin10_runner._interpret_flash({"id": "1", "content": "市场快讯测试"})

    assert response["success"] is True
    assert calls == [("opencode", "nemotron-3-ultra-free")]
    assert response["data"]["model"] == "nemotron-3-ultra-free"
    assert response["data"]["model_source"] == "llm_settings"
    assert "opencode" in response["data"]["cache_key"]
    assert "nemotron-3-ultra-free" in response["data"]["cache_key"]


def test_stock_evidence_is_stock_specific_and_uses_effective_model():
    from scripts.stock_evidence import analyze_stock_evidence

    cache = FakeCache()
    captured = {}

    class FakeValuationService:
        def analyze(self, code):
            assert code == "300450"
            return {
                "code": code,
                "name": "先导智能",
                "data_signature": "signature-300450",
                "current_price": 20.5,
                "consensus": {"final_mid": 23.0, "confidence": 0.68},
                "valuations": {"absolute": {"status": "success", "mid": 22.0}},
                "data_quality": {"status": "partial"},
            }

    def fake_chat_json(provider, system, user, **kwargs):
        captured.update(provider=provider, user=user, model=kwargs.get("model"))
        return {
            "success": True,
            "model": "nemotron-3-ultra-free",
            "usage": {},
            "data": {
                "evidence_views": [
                    {"title": "估值证据", "focus": "价格与价值", "view": "存在安全边际"},
                    {"title": "风险证据", "focus": "数据质量", "view": "财务数据部分缺失"},
                ],
                "overall": "仅供研究复核",
                "confidence": 0.66,
                "risks": ["数据完整度"],
            },
        }

    result = analyze_stock_evidence(
        "300450",
        "先导智能",
        cache=cache,
        valuation_service=FakeValuationService(),
        chat_json_fn=fake_chat_json,
        selection={
            "provider": "opencode",
            "model": "nemotron-3-ultra-free",
            "source": "llm_settings",
            "registry_version": 1,
        },
    )

    assert captured["provider"] == "opencode"
    assert captured["model"] == "nemotron-3-ultra-free"
    assert "300450" in captured["user"]
    assert result["code"] == "300450"
    assert result["provider"] == "opencode"
    assert result["model"] == "nemotron-3-ultra-free"
    assert result["model_source"] == "llm_settings"
    assert result["evidenceViews"][0]["title"] == "估值证据"


def test_stock_evidence_snapshot_excludes_large_valuation_details():
    from scripts.stock_evidence import _bounded_snapshot

    snapshot = _bounded_snapshot({
        "code": "300450",
        "consensus": {"final_mid": 20, "calibration": {"large": list(range(1000))}},
        "valuations": {
            "absolute": {
                "status": "success",
                "low": 18,
                "mid": 20,
                "high": 22,
                "details": {"large": list(range(1000))},
            },
        },
    })

    encoded = json.dumps(snapshot, ensure_ascii=False)
    assert len(encoded) < 3000
    assert "large" not in encoded


def test_frontend_model_contract_uses_registry_and_stock_specific_action():
    db_panel = (ROOT / "components" / "DbPanel.tsx").read_text(encoding="utf-8")
    jin10 = (ROOT / "components" / "Jin10DataPanel.tsx").read_text(encoding="utf-8")
    catalog = json.loads((ROOT / "config" / "llm_models.json").read_text(encoding="utf-8"))

    assert catalog["schema_version"] == 1
    assert not (ROOT / "components" / "AutonomousSchedulingDrawer.tsx").exists()
    assert "action: 'ai_stock_evidence'" in db_panel
    assert "code: stock.code" in db_panel
    assert "modelSource" in jin10
