from scripts import llm_client


def test_opencode_models_normalize_without_changing_glm(monkeypatch):
    payloads = []
    monkeypatch.setattr(llm_client, "get_api_key", lambda provider: "test-key")
    monkeypatch.setattr(llm_client, "_record_usage_safe", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        llm_client,
        "_single_call",
        lambda endpoint, api_key, payload, timeout: payloads.append(payload) or {
            "choices": [{"message": {"content": "OK"}}], "usage": {}
        },
    )
    assert llm_client.chat("opencode", "system", "user", model="deepseek")["success"] is True
    assert llm_client.chat("glm", "system", "user", model="glm-5.2")["success"] is True
    assert payloads[0]["model"] == "deepseek-v4-flash-free"
    assert payloads[1]["model"] == "glm-5.2"


def test_glm_base_urls_normalize_to_chat_endpoint(monkeypatch):
    monkeypatch.setenv("GLM_BASE_URL", "https://api.ifanr.work/")
    assert llm_client._resolve_endpoint(llm_client.PROVIDERS["glm"]) == "https://api.ifanr.work/v1/chat/completions"
