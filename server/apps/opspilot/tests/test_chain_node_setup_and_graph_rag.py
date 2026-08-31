"""ToolsNodes setup / 知识路由 / GraphRAG：失败不中断、空检索返回空。"""
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

for _mod_name in ("oracledb", "pyodbc"):
    sys.modules.setdefault(_mod_name, types.ModuleType(_mod_name))

import pytest

from apps.opspilot.metis.llm.chain.entity import DoneToolConfig
from apps.opspilot.metis.llm.chain.node import BasicNode, ToolsNodes

pytestmark = pytest.mark.unit


def test_select_knowledge_ids_parses_isolated_llm_json():
    node = BasicNode()
    request = SimpleNamespace(user_message="查主机")
    config = {
        "configurable": {
            "km_info": [{"id": "kb-1"}],
            "km_route_llm_model": "m",
            "km_route_llm_api_base": "http://x",
            "km_route_llm_api_key": "k",
            "graph_request": request,
        }
    }
    with (
        patch("apps.opspilot.metis.llm.chain.node.TemplateLoader.render_template", return_value="prompt"),
        patch("apps.opspilot.metis.llm.chain.node.LLMClientFactory.invoke_isolated", return_value='["kb-1"]'),
    ):
        assert node._select_knowledge_ids(config) == ["kb-1"]


@pytest.mark.asyncio
async def test_execute_graph_rag_empty_and_exception():
    node = BasicNode()
    req = SimpleNamespace(graph_rag_request=SimpleNamespace(group_ids=["g1"], search_query="q"))
    with patch.object(node, "_perform_graph_search", new=AsyncMock(return_value=[])):
        assert await node._execute_graph_rag(req, {}) == []
    with patch.object(node, "_perform_graph_search", new=AsyncMock(side_effect=RuntimeError("down"))):
        assert await node._execute_graph_rag(req, {}) == []


@pytest.mark.asyncio
async def test_perform_graph_search_sets_query_and_returns():
    node = BasicNode()
    graph_req = SimpleNamespace(group_ids=["g1"], search_query="")
    rag_req = SimpleNamespace(search_query="主机宕机", graph_rag_request=graph_req)
    rag = MagicMock()
    rag.search = AsyncMock(return_value=[{"fact": "a->b"}])
    with patch("apps.opspilot.metis.llm.chain.node.GraphitiRAG", return_value=rag):
        out = await node._perform_graph_search(rag_req, {})
    assert out == [{"fact": "a->b"}]
    assert graph_req.search_query == "主机宕机"


def test_resolve_transport_and_k8s_greeting_filter():
    assert ToolsNodes._resolve_remote_transport("http://x", "streamable_http") == "streamable_http"
    assert ToolsNodes._resolve_remote_transport("http://x/tools?transport=sse") == "sse"
    assert ToolsNodes._resolve_remote_transport("http://x/v1/mcp") == "streamable_http"
    assert ToolsNodes._resolve_remote_transport("http://x/api") == "sse"
    k8s = SimpleNamespace(url="langchain:kubernetes")
    other = SimpleNamespace(url="langchain:mysql")
    assert ToolsNodes._is_k8s_tool_server(k8s) is True
    assert ToolsNodes._is_k8s_tool_server(other) is False
    node = ToolsNodes()
    assert node._should_apply_first_turn_greeting_filter(SimpleNamespace(tools_servers=[])) is False
    assert node._should_apply_first_turn_greeting_filter(SimpleNamespace(tools_servers=[k8s])) is True
    assert node._should_apply_first_turn_greeting_filter(SimpleNamespace(tools_servers=[k8s, other])) is False


@pytest.mark.asyncio
async def test_setup_loads_langchain_and_continues_on_mcp_failure():
    node = ToolsNodes()
    node.get_llm_client = MagicMock(return_value=MagicMock())
    lc_tool = SimpleNamespace(name="list_pods", description="pods")
    servers = [
        SimpleNamespace(
            name="k8s",
            url="langchain:kubernetes",
            extra_tools_prompt="k8s tools",
            extra_param_prompt="",
            enable_auth=False,
            auth_token="",
            command="",
            args=[],
            transport="",
        ),
        SimpleNamespace(
            name="mcp",
            url="http://mcp/sse",
            extra_tools_prompt="",
            extra_param_prompt="",
            enable_auth=True,
            auth_token="tok",
            command="",
            args=[],
            transport="sse",
        ),
    ]
    request = SimpleNamespace(tools_servers=servers, tool_pool_config=None)
    mcp_client = MagicMock()
    mcp_client.get_tools = AsyncMock(side_effect=RuntimeError("mcp down"))
    with (
        patch("apps.opspilot.metis.llm.chain.node.ToolsLoader.load_tools", return_value=[lc_tool]),
        patch("apps.opspilot.metis.llm.chain.node.MultiServerMCPClient", return_value=mcp_client),
    ):
        await node.setup(request)
    assert any(t.name == "list_pods" for t in node.tools)
    assert node.tool_catalog["kubernetes"] == ["list_pods"]
    assert node.mcp_config["mcp"]["headers"]["Authorization"] == "tok"
    assert node.all_tools


def test_done_tool_returns_result_string():
    node = ToolsNodes()
    assert node._build_done_tool() is None
    tool = node._build_done_tool(DoneToolConfig(enabled=True))
    assert tool.invoke({"result": "已完成巡检"}) == "已完成巡检"
