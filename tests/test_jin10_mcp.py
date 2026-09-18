import pytest

from quant.data.jin10_mcp import Jin10MCPClient, MCPProtocolError, page_info
from scripts import jin10_runner
from scripts.jin10_runner import ResilientJin10MCPClient


class FakeTransport:
    def __init__(self):
        self.calls = []

    def __call__(self, payload, headers, timeout):
        self.calls.append({"payload": payload, "headers": dict(headers), "timeout": timeout})
        method = payload["method"]
        if method == "initialize":
            return 200, {"Mcp-Session-Id": "sid-1"}, {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {"protocolVersion": "2025-11-25", "capabilities": {}},
            }
        if method == "notifications/initialized":
            return 202, {}, ""
        if method == "tools/list":
            return 200, {}, {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {"tools": [{"name": "get_quote"}, {"name": "list_flash"}]},
            }
        if method == "resources/list":
            return 200, {}, {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {"resources": [{"uri": "quote://codes"}]},
            }
        if method == "resources/read":
            return 200, {}, {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {"structuredContent": {"data": [{"code": "XAUUSD", "name": "现货黄金"}]}},
            }
        if method == "tools/call":
            return 200, {}, {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "structuredContent": {
                        "data": {"code": "XAUUSD", "name": "现货黄金", "close": 3333.3}
                    },
                    "content": [{"type": "text", "text": "human-readable quote"}],
                },
            }
        raise AssertionError(method)


def test_standard_mcp_flow_prefers_structured_content():
    transport = FakeTransport()
    client = Jin10MCPClient(token="test-token", transport=transport)

    tools = client.list_tools()
    quote = client.call_tool("get_quote", {"code": "XAUUSD"})

    methods = [c["payload"]["method"] for c in transport.calls]
    assert methods[:3] == ["initialize", "notifications/initialized", "tools/list"]
    assert methods[-1] == "tools/call"
    assert transport.calls[-1]["headers"]["Mcp-Session-Id"] == "sid-1"
    assert tools["tools"][0]["name"] == "get_quote"
    assert quote["success"] is True
    assert quote["data"]["data"]["code"] == "XAUUSD"
    assert quote["content"][0]["text"] == "human-readable quote"


def test_client_can_use_query_authenticated_endpoint_without_bearer_header():
    transport = FakeTransport()
    client = Jin10MCPClient(
        server_url="https://api.example/mcp/?token=secret",
        token="",
        require_bearer=False,
        transport=transport,
    )

    client.list_tools()

    assert "Authorization" not in transport.calls[0]["headers"]


def test_resource_read_uses_structured_content():
    transport = FakeTransport()
    client = Jin10MCPClient(token="test-token", transport=transport)

    resources = client.list_resources()
    codes = client.read_resource("quote://codes")

    assert resources["resources"][0]["uri"] == "quote://codes"
    assert codes["success"] is True
    assert codes["data"]["data"][0]["code"] == "XAUUSD"


def test_pagination_contract_uses_cursor_next_cursor_has_more():
    page = {"data": {"items": [1, 2], "next_cursor": "n2", "has_more": True}}

    assert page_info(page) == {"items": [1, 2], "next_cursor": "n2", "has_more": True}


def test_json_rpc_error_is_protocol_error():
    def transport(payload, headers, timeout):
        return 200, {}, {
            "jsonrpc": "2.0",
            "id": payload.get("id"),
            "error": {"code": -32601, "message": "method not found"},
        }

    client = Jin10MCPClient(token="test-token", transport=transport)
    with pytest.raises(MCPProtocolError):
        client.list_tools()


def test_expired_session_reinitializes_once_and_retries_tool_call():
    calls = []
    initialize_count = 0

    def transport(payload, headers, timeout):
        nonlocal initialize_count
        calls.append({"method": payload["method"], "headers": dict(headers)})
        method = payload["method"]
        if method == "initialize":
            initialize_count += 1
            session_id = f"sid-{initialize_count}"
            return 200, {"Mcp-Session-Id": session_id}, {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {"protocolVersion": "2025-11-25", "capabilities": {}},
            }
        if method == "notifications/initialized":
            return 202, {}, ""
        if method == "tools/call" and initialize_count == 1:
            return 404, {}, {
                "jsonrpc": "2.0",
                "error": {"code": -32001, "message": "session not found"},
            }
        if method == "tools/call":
            return 200, {}, {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "structuredContent": {
                        "data": {"code": "XAUUSD", "close": "4074.91"}
                    }
                },
            }
        raise AssertionError(method)

    client = ResilientJin10MCPClient(token="test-token", transport=transport)
    quote = client.call_tool("get_quote", {"code": "XAUUSD"})

    assert quote["success"] is True
    assert quote["data"]["data"]["code"] == "XAUUSD"
    assert [call["method"] for call in calls] == [
        "initialize",
        "notifications/initialized",
        "tools/call",
        "initialize",
        "notifications/initialized",
        "tools/call",
    ]
    assert calls[3]["headers"].get("Mcp-Session-Id") is None
    assert calls[-1]["headers"]["Mcp-Session-Id"] == "sid-2"


class FakePagedClient:
    def __init__(self):
        self.page_calls = []

    def fetch_all_pages(self, tool_name, arguments=None, limit_pages=5):
        self.page_calls.append((tool_name, arguments or {}, limit_pages))
        return {
            "success": True,
            "data": {
                "data": {
                    "items": [{"id": index} for index in range(limit_pages * 20)],
                    "next_cursor": "",
                    "has_more": False,
                }
            },
        }


def test_status_reports_degraded_health_when_mcp_transport_is_unavailable(monkeypatch):
    class OfflineClient:
        server_url = "https://example.invalid/mcp"
        protocol_version = "2025-11-25"

        def initialize(self):
            raise OSError("getaddrinfo failed")

    monkeypatch.setattr(jin10_runner, "_client", lambda: OfflineClient())

    result = jin10_runner.handle({"action": "status", "force_refresh": True})

    assert result["success"] is True
    assert result["data"]["healthy"] is False
    assert result["data"]["degraded"] is True
    assert result["data"]["reason_code"] == "mcp_transport_unavailable"
    assert result["data"]["tools"] == []
    assert result["data"]["resources"] == []


def test_runner_flash_deep_load_uses_ten_cursor_pages(monkeypatch):
    client = FakePagedClient()
    monkeypatch.setattr(jin10_runner, "_client", lambda: client)

    result = jin10_runner.handle({
        "action": "flash",
        "pages": 10,
        "force_refresh": True,
    })

    assert result["success"] is True
    assert client.page_calls == [("list_flash", {}, 10)]
    assert len(result["data"]["data"]["items"]) == 200


def test_runner_news_page_count_is_clamped_to_ten(monkeypatch):
    client = FakePagedClient()
    monkeypatch.setattr(jin10_runner, "_client", lambda: client)

    result = jin10_runner.handle({
        "action": "news",
        "pages": 999,
        "force_refresh": True,
    })

    assert result["success"] is True
    assert client.page_calls == [("list_news", {}, 10)]
    assert len(result["data"]["data"]["items"]) == 200
