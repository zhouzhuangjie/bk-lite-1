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
    assert client._parse_anyof_schema({"anyOf": [{"type": "string"}]}) == {}


def test_get_tools_wraps_fetch_failure():
    client = MCPClient("http://x")
    client._mcp_client = MagicMock()
    with patch.object(client, "_fetch_tools_async", side_effect=RuntimeError("down")):
        with pytest.raises(RuntimeError, match="Failed to get tools: down"):
            client.get_tools()


def test_fetch_tools_async_uses_running_loop():
    client = MCPClient("http://x", timeout=1.5)
    client._mcp_client = MagicMock()
    fut = MagicMock()
    fut.result.return_value = ["t1"]
    loop = MagicMock()
    with (
        patch("apps.opspilot.services.mcp_client.asyncio.get_running_loop", return_value=loop),
        patch("apps.opspilot.services.mcp_client.asyncio.run_coroutine_threadsafe", return_value=fut) as rcts,
    ):
        out = client._fetch_tools_async()
    assert out == ["t1"]
    rcts.assert_called_once()
    fut.result.assert_called_once_with(timeout=1.5)


def test_fetch_tools_async_falls_back_to_asyncio_run():
    client = MCPClient("http://x")
    client._mcp_client = MagicMock()
    client._mcp_client.get_tools.return_value = "coro"
    with (
        patch("apps.opspilot.services.mcp_client.asyncio.get_running_loop", side_effect=RuntimeError("no running loop")),
        patch("apps.opspilot.services.mcp_client.asyncio.run", return_value=["t2"]) as run,
    ):
        out = client._fetch_tools_async()
    assert out == ["t2"]
    run.assert_called_once_with("coro")


def test_extract_input_schema_from_model_and_args():
    client = MCPClient("http://x")

    class Schema:
        def schema(self):
            return {"properties": {"q": {"type": "string"}}, "required": ["q"]}

    tool = SimpleNamespace(input_schema=Schema(), args_schema=None)
    parsed = client._extract_input_schema(tool)
    assert parsed["required"] == ["q"]

    tool_args = SimpleNamespace(input_schema=None, args_schema=Schema())
    assert client._extract_input_schema(tool_args)["required"] == ["q"]
    assert client._extract_input_schema(SimpleNamespace()) == {}


def test_schema_to_input_schema_variants():
    class WithSchema:
        def schema(self):
            return {"a": 1}

    class WithModel:
        def model_json_schema(self):
            return {"b": 2}

    class Boom:
        def schema(self):
            raise RuntimeError("broken")

    assert MCPClient._schema_to_input_schema(WithSchema()) == {"a": 1}
    assert MCPClient._schema_to_input_schema(WithModel()) == {"b": 2}
    assert MCPClient._schema_to_input_schema(object()) == {}
    assert MCPClient._schema_to_input_schema(Boom()) == {}
