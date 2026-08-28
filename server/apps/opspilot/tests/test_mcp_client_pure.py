"""MCPClient：传输协议解析、认证头、schema 转 parameters。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.opspilot.services.mcp_client import MCPClient

pytestmark = pytest.mark.unit


def test_resolve_transport_explicit_query_and_path():
    assert MCPClient("http://x", transport="streamable_http")._resolve_transport() == "streamable_http"
    assert MCPClient("http://x/tools?transport=sse")._resolve_transport() == "sse"
    assert MCPClient("http://x/v1/sse")._resolve_transport() == "sse"
    assert MCPClient("http://x/v1/mcp")._resolve_transport() == "streamable_http"
    assert MCPClient("http://x/api")._resolve_transport() == "sse"


def test_context_manager_rejects_stdio_and_sets_auth_header():
    with pytest.raises(ValueError, match="stdio-mcp"):
        with MCPClient("stdio-mcp://local"):
            pass
    with patch("apps.opspilot.services.mcp_client.MultiServerMCPClient") as ctor:
        with MCPClient("http://mcp/sse", enable_auth=True, auth_token="abc") as client:
            cfg = ctor.call_args[0][0]["default"]
            assert cfg["headers"]["Authorization"] == "Basic abc"
            assert cfg["transport"] == "sse"
            assert client._mcp_client is ctor.return_value
        with MCPClient("http://mcp", enable_auth=True, auth_token="Bearer tok") as client:
            assert ctor.call_args[0][0]["default"]["headers"]["Authorization"] == "Bearer tok"


def test_get_tools_requires_context_and_converts_schema():
    client = MCPClient("http://x")
    with pytest.raises(RuntimeError, match="context manager"):
        client.get_tools()

    tool = SimpleNamespace(
        name="search",
        description="find",
        input_schema={"properties": {"q": {"type": "string", "description": "query"}}, "required": ["q"]},
    )
    client._mcp_client = MagicMock()
    with patch.object(client, "_fetch_tools_async", return_value=[tool]):
        out = client.get_tools()
    assert out[0]["name"] == "search"
    assert out[0]["parameters"]["q"]["required"] is True

    anyof = {
        "anyOf": [
            {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]},
        ]
    }
    assert "x" in client._parse_anyof_schema(anyof)
    ref = {
        "anyOf": [{"$ref": "#/$defs/In"}],
        "$defs": {"In": {"properties": {"y": {"type": "string", "enum": ["a"]}}, "required": []}},
    }
    parsed = client._parse_anyof_schema(ref)
    assert parsed["y"]["enum"] == ["a"]
    extra = {"anyOf": [{"type": "object", "additionalProperties": True}]}
    assert "__any__" in client._parse_anyof_schema(extra)
