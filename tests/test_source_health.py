from quant.data import source_health
from quant.data.source_health import build_source_health


def test_build_source_health_never_marks_unchecked_sources_online():
    health = build_source_health(
        {
            "tdx_quant": {"ok": True, "latency_ms": 12},
            "sina": {"ok": False, "error": "timeout", "latency_ms": 5000},
            "tushare": {"configured": False},
        },
        checked_at="2026-07-13T10:30:00",
    )

    by_id = {item["id"]: item for item in health["sources"]}
    assert by_id["tdx_quant"]["status"] == "online"
    assert by_id["sina"]["status"] == "offline"
    assert by_id["tushare"]["status"] == "unconfigured"
    assert by_id["tencent"]["status"] == "unknown"
    assert health["summary"] == {
        "online": 1,
        "offline": 1,
        "unconfigured": 1,
        "unknown": 5,
    }


def test_probe_sources_checks_configured_mcp_endpoints(monkeypatch):
    monkeypatch.setenv("JIN10_MCP_SERVER_URL", "https://mcp.jin10.example/mcp")
    monkeypatch.setenv("JIN10_MCP_BEARER_TOKEN", "jin10-secret")
    monkeypatch.setenv(
        "TUSHARE_MCP_SERVER_URL",
        "https://api.tushare.example/mcp/?token=tushare-secret",
    )
    monkeypatch.setattr(
        source_health,
        "_probe_jin10_mcp",
        lambda: {"available": True, "tool_count": 8},
    )
    monkeypatch.setattr(
        source_health,
        "_probe_tushare_mcp",
        lambda: {"available": True, "tool_count": 4},
    )
    monkeypatch.setattr(
        source_health,
        "_probe_cninfo_disclosures",
        lambda: {"available": True, "announcement_count": 1},
    )
    monkeypatch.setattr(
        source_health,
        "_timed_probe",
        lambda probe: {"ok": bool(probe().get("available")), "latency_ms": 1},
    )
    monkeypatch.setattr(
        source_health,
        "_module_probe",
        lambda module_name: {"ok": True, "latency_ms": 0},
    )

    health = source_health.probe_sources()
    by_id = {item["id"]: item for item in health["sources"]}

    assert by_id["jin10"]["status"] == "online"
    assert by_id["tushare"]["status"] == "online"
    assert by_id["cninfo"]["name"] == "巨潮公告"
    assert by_id["cninfo"]["status"] == "online"


def test_mcp_probe_errors_redact_query_tokens():
    error = source_health._safe_probe_error(
        "MCP transport failed for https://api.example/mcp/?token=top-secret&x=1"
    )

    assert "top-secret" not in error
    assert "token=%2A%2A%2A" in error
