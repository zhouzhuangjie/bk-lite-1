"""ToolsNodes / BasicNode：RAG 节点、工具激活、done/choice/approval、LLM chat。

对照契约：空检索直接返回；图片文档不混入文本 RAG；动态工具按类别激活；
done 关闭时不注册；choice 被 guard 拦截时不进入等待；chat 节点把 LLM 回复写入 messages。
"""
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

for _mod_name in ("oracledb", "pyodbc"):
    sys.modules.setdefault(_mod_name, types.ModuleType(_mod_name))
_falkordb = types.ModuleType("falkordb")
_falkordb.Graph = type("Graph", (), {})
sys.modules.setdefault("falkordb", _falkordb)
_falkordb_asyncio = types.ModuleType("falkordb.asyncio")
_falkordb_asyncio.FalkorDB = type("FalkorDB", (), {})
sys.modules.setdefault("falkordb.asyncio", _falkordb_asyncio)

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from apps.opspilot.metis.llm.chain.entity import DoneToolConfig
from apps.opspilot.metis.llm.chain.node import BasicNode, ToolsNodes

pytestmark = pytest.mark.unit


def test_prompt_message_node_appends_system_prompt():
    node = BasicNode()
    request = SimpleNamespace(system_message_prompt="你是助手")
    with patch(
        "apps.opspilot.metis.llm.chain.node.TemplateLoader.render_template",
        return_value="渲染后的系统提示",
    ):
        state = {"messages": []}
        out = node.prompt_message_node(state, {"configurable": {"graph_request": request}})
    assert out is state
    assert isinstance(state["messages"][0], SystemMessage)
    assert state["messages"][0].content == "渲染后的系统提示"


def test_chat_node_invokes_llm_and_returns_message():
    node = BasicNode()
    llm = MagicMock()
    reply = AIMessage(content="pong")
    llm.invoke.return_value = reply
    with patch.object(node, "get_llm_client", return_value=llm):
        result = node.chat_node(
            {"messages": [HumanMessage(content="ping")]},
            {"configurable": {"graph_request": SimpleNamespace()}},
        )
    assert result == {"messages": reply}
    llm.invoke.assert_called_once()


def test_add_image_docs_skips_missing_base64_and_appends_valid():
    node = BasicNode()
    state = {"messages": []}
    node._add_image_docs_to_messages(state, [])
    assert state["messages"] == []

    docs = [
        SimpleNamespace(metadata={}),
        SimpleNamespace(metadata={"image_base64": "abc123", "page": 2}),
    ]
    node._add_image_docs_to_messages(state, docs)
    assert len(state["messages"]) == 1
    content = state["messages"][0].content
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"].startswith("data:image/jpeg;base64,abc123")


@pytest.mark.asyncio
async def test_naive_rag_node_empty_request_returns_state():
    node = BasicNode()
    state = {"messages": []}
    request = SimpleNamespace(naive_rag_request=[])
    out = await node.naive_rag_node(state, {"configurable": {"graph_request": request}})
    assert out is state
    assert state["messages"] == []


@pytest.mark.asyncio
async def test_naive_rag_node_skips_unselected_index_and_separates_images():
    node = BasicNode()
    selected = ["kb-keep"]
    skipped = SimpleNamespace(index_name="kb-skip", search_query="", enable_graph_rag=False)
    kept = SimpleNamespace(index_name="kb-keep", search_query="", enable_graph_rag=False)
    request = SimpleNamespace(naive_rag_request=[skipped, kept], graph_user_message="q")

    text_doc = SimpleNamespace(page_content="手册正文", metadata={"is_doc": "1"})
    img_doc = SimpleNamespace(
        page_content="图中文字",
        metadata={"format": "image", "image_base64": "img==", "page": 1},
    )

    rag = MagicMock()
    rag.search.return_value = [text_doc, img_doc]

    async def _to_thread(func, *args, **kwargs):
        if func == node._select_knowledge_ids:
            return selected
        return func(*args, **kwargs)

    with (
        patch("apps.opspilot.metis.llm.chain.node.asyncio.to_thread", side_effect=_to_thread),
        patch("apps.opspilot.metis.llm.chain.node.PgvectorRag", return_value=rag),
        patch(
            "apps.opspilot.metis.llm.chain.node.TemplateLoader.render_template",
            return_value="RAG提示",
        ),
    ):
        state = {"messages": []}
        await node.naive_rag_node(
            state,
            {"configurable": {"graph_request": request, "km_info": [{"id": "kb-keep"}]}},
        )

    rag.search.assert_called_once_with(kept)
    texts = [m.content if isinstance(m.content, str) else str(m.content) for m in state["messages"]]
    assert any("RAG提示" in t or "图片识别内容" in t for t in texts)
    assert any(
        isinstance(m.content, list) and m.content[0]["type"] == "image_url" for m in state["messages"]
    )


def test_normalize_repair_group_by_aliases():
    assert ToolsNodes._normalize_repair_group_by("category") == "category"
    assert ToolsNodes._normalize_repair_group_by("按工作负载") == "target"
    assert ToolsNodes._normalize_repair_group_by("问题类别") == "category"
    assert ToolsNodes._normalize_repair_group_by("一次性全部") == "all"
    assert ToolsNodes._normalize_repair_group_by("???") == "target"


def test_sanitize_duplicate_config_analysis_text_requires_capability_and_markers():
    node = ToolsNodes()
    node._skill_package_capabilities = set()
    original = AIMessage(content="配置检查报告\nHigh Severity")
    assert node._sanitize_duplicate_config_analysis_text(original, {"deployments": [{}]}) is original

    node._skill_package_capabilities = {"config_analysis_report"}
    sanitized = node._sanitize_duplicate_config_analysis_text(original, {"deployments": [{}]})
    assert sanitized is not original
    assert "结构化卡片" in sanitized.content

    short = AIMessage(content="仅一句")
    assert node._sanitize_duplicate_config_analysis_text(short, {"deployments": [{}]}) is short


def test_activate_tools_meta_tool_activates_and_reports_missing():
    node = ToolsNodes()
    t1 = SimpleNamespace(name="list_pods", description="pods")
    t2 = SimpleNamespace(name="get_logs", description="logs")
    node.tool_catalog = {"kubernetes": ["list_pods", "get_logs"]}
    node.tool_catalog_descriptions = {"kubernetes": "K8s 工具"}
    node._category_tool_map = {"kubernetes": [t1, t2]}
    node.active_tools = []

    tool = node._build_activate_tools_meta_tool()
    first = tool.invoke({"categories": "kubernetes,missing"})
    assert "已激活: kubernetes (2 个工具)" in first
    assert "未找到: missing" in first
    assert {t.name for t in node.active_tools} == {"list_pods", "get_logs"}

    again = tool.invoke({"categories": "kubernetes"})
    assert "已存在: kubernetes" in again


def test_done_tool_disabled_returns_none_and_enabled_echoes_result():
    node = ToolsNodes()
    assert node._build_done_tool(DoneToolConfig(enabled=False)) is None
    tool = node._build_done_tool(DoneToolConfig(enabled=True, tool_name="__done__"))
    assert tool.name == "__done__"
    assert tool.invoke({"result": '{"ok": true}'}) == '{"ok": true}'


@pytest.mark.asyncio
async def test_choice_tool_guard_rejects_without_waiting():
    node = ToolsNodes()
    tool = node._build_choice_tool()
    with (
        patch(
            "apps.opspilot.metis.llm.tools.kubernetes.user_choice_guard.build_kubernetes_cluster_choice_guard",
            return_value=object(),
        ),
        patch(
            "apps.opspilot.metis.llm.tools.common.user_choice_guard.validate_user_choice_options",
            return_value="选项不合法",
        ),
        patch("apps.opspilot.metis.llm.chain.node.wait_for_choice") as wait,
    ):
        result = await tool.coroutine(question="选哪个？", question_type="single_select", options=["a"])
    assert result == "选项不合法"
    wait.assert_not_called()


@pytest.mark.asyncio
async def test_choice_tool_confirm_returns_user_yes():
    node = ToolsNodes()
    tool = node._build_choice_tool()
    with (
        patch(
            "apps.opspilot.metis.llm.tools.kubernetes.user_choice_guard.build_kubernetes_cluster_choice_guard",
            return_value=None,
        ),
        patch(
            "apps.opspilot.metis.llm.tools.common.user_choice_guard.validate_user_choice_options",
            return_value="",
        ),
        patch("apps.opspilot.metis.llm.chain.node.dispatch_custom_event"),
        patch(
            "apps.opspilot.metis.llm.chain.node.wait_for_choice",
            new=AsyncMock(return_value={"selected": ["yes"], "source": "user"}),
        ),
    ):
        result = await tool.coroutine(question="确认重启？", question_type="confirm", options=None)
    assert result.startswith("用户回答: 是")


@pytest.mark.asyncio
async def test_approval_tool_approve_and_deny():
    node = ToolsNodes()
    tool = node._build_approval_tool()
    with (
        patch("apps.opspilot.metis.llm.chain.node.dispatch_custom_event"),
        patch(
            "apps.opspilot.metis.llm.chain.node.wait_for_approval",
            new=AsyncMock(return_value={"decision": "approve", "reason": ""}),
        ),
    ):
        approved = await tool.coroutine(action="删除 Pod", reason="高危", risk_level="high")
    assert "已批准" in approved
    assert "删除 Pod" in approved

    with (
        patch("apps.opspilot.metis.llm.chain.node.dispatch_custom_event", side_effect=RuntimeError("no graph")),
        patch(
            "apps.opspilot.metis.llm.chain.node.wait_for_approval",
            new=AsyncMock(return_value={"decision": "deny", "reason": "业务窗口"}),
        ),
    ):
        denied = await tool.coroutine(action="删库", reason="破坏性", risk_level="critical")
    assert "操作被拒绝" in denied
    assert "业务窗口" in denied


@pytest.mark.asyncio
async def test_setup_loads_langchain_and_mcp_and_enables_dynamic_mode():
    node = ToolsNodes()
    k8s_tool = SimpleNamespace(name="list_pods", description="list pods in cluster")
    mcp_tool = SimpleNamespace(name="search_docs", description="search")

    langchain_server = SimpleNamespace(
        url="langchain:kubernetes",
        name="k8s",
        extra_tools_prompt="k8s tools",
        extra_param_prompt="",
        enable_auth=False,
        auth_token="",
        command="",
        args=[],
        transport="",
    )
    mcp_server = SimpleNamespace(
        url="https://mcp.example/sse",
        name="docs",
        extra_tools_prompt="",
        extra_param_prompt="",
        enable_auth=True,
        auth_token="Bearer t",
        command="",
        args=[],
        transport="",
    )
    request = SimpleNamespace(
        tools_servers=[langchain_server, mcp_server],
        tool_pool_config=SimpleNamespace(enabled=True, auto_activate_threshold=0),
        done_tool_config=DoneToolConfig(enabled=False),
        extra_config={"skill_package_capabilities": ["repair_diff_report"]},
    )

    mcp_client = AsyncMock()
    mcp_client.get_tools.return_value = [mcp_tool]

    with (
        patch.object(node, "get_llm_client", return_value=MagicMock()),
        patch("apps.opspilot.metis.llm.chain.node.StructuredOutputParser"),
        patch("apps.opspilot.metis.llm.chain.node.MultiServerMCPClient", return_value=mcp_client),
        patch(
            "apps.opspilot.metis.llm.chain.node.ToolsLoader.load_tools",
            return_value=[k8s_tool],
        ),
    ):
        await node.setup(request)

    assert node._dynamic_mode is True
    assert node.tools == []
    assert {t.name for t in node.all_tools} >= {"list_pods", "search_docs"}
    assert node.mcp_config["docs"]["headers"]["Authorization"] == "Bearer t"
    assert node.mcp_config["docs"]["transport"] == "sse"
    assert node._enable_repair_diff_report() is True
    assert node._enable_config_analysis_report() is False
