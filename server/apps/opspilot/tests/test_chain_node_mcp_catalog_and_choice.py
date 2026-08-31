"""ToolsNodes：MCP catalog 归类、choice 文案、嵌套 patch/YAML 助手。

对照契约：单 MCP server 把未归类工具挂到 server 名下；多 MCP 无法精确归属时
统一进 ``mcp_tools``；choice 按 question_type 生成确认/文本/多选文案；
``_extract_patch_body`` / ``_json_to_yaml`` 从 kubectl patch 命令抽出 JSON 并转 YAML。
不连真实 K8s / MCP。
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

from apps.opspilot.metis.llm.chain.node import ToolsNodes

pytestmark = pytest.mark.unit


def _find_code(code, name):
    """从嵌套 code object 中定位闭包函数（保持原文件名/行号，覆盖率计入 node.py）。"""
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            if const.co_name == name:
                return const
            found = _find_code(const, name)
            if found:
                return found
    return None


def _cell(value=None):
    return (lambda x: lambda: x)(value).__closure__[0]


def _nested_fn(owner_code, name, extra_globals=None):
    code = _find_code(owner_code, name)
    assert code is not None, f"找不到嵌套函数 {name}"
    ns = dict(extra_globals or {})
    cells = tuple(_cell(None) for _ in code.co_freevars) if code.co_freevars else None
    fn = types.FunctionType(code, ns, name, None, cells)
    ns[name] = fn
    if cells:
        for i, varname in enumerate(code.co_freevars):
            cells[i].cell_contents = fn if varname == name else ns.get(varname)
    return fn


def _mcp_server(name, url, extra_tools_prompt="", enable_auth=False, auth_token=""):
    return SimpleNamespace(
        name=name,
        url=url,
        extra_tools_prompt=extra_tools_prompt,
        extra_param_prompt="",
        enable_auth=enable_auth,
        auth_token=auth_token,
        command="",
        args=[],
        transport="",
    )


@pytest.mark.asyncio
async def test_setup_single_mcp_catalog_uses_server_name_and_prompt():
    """单 MCP server：未归类工具进入该 server 类别，描述优先 extra_tools_prompt。"""
    node = ToolsNodes()
    mcp_tool = SimpleNamespace(name="search_docs", description="search remote docs")
    request = SimpleNamespace(
        tools_servers=[_mcp_server("docs", "https://mcp.example/sse", extra_tools_prompt="文档检索")],
        tool_pool_config=None,
        extra_config={"_require_choice_before_tools": True, "_multi_instance_options": ["a"]},
    )
    mcp_client = AsyncMock()
    mcp_client.get_tools.return_value = [mcp_tool]
    with (
        patch.object(node, "get_llm_client", return_value=MagicMock()),
        patch("apps.opspilot.metis.llm.chain.node.StructuredOutputParser"),
        patch("apps.opspilot.metis.llm.chain.node.MultiServerMCPClient", return_value=mcp_client),
    ):
        await node.setup(request)
    assert node.tool_catalog["docs"] == ["search_docs"]
    assert node.tool_catalog_descriptions["docs"] == "文档检索"
    assert [t.name for t in node._category_tool_map["docs"]] == ["search_docs"]
    assert node._require_choice_before_tools is True
    assert node._multi_instance_options == ["a"]
    assert node._dynamic_mode is False
    assert node.active_tools == node.all_tools


@pytest.mark.asyncio
async def test_setup_multi_mcp_catalog_collapses_to_mcp_tools():
    """多 MCP server：无法精确归属时统一进 mcp_tools，并写明工具/server 数量。"""
    node = ToolsNodes()
    tools = [
        SimpleNamespace(name="alpha", description="a"),
        SimpleNamespace(name="beta", description="b"),
    ]
    request = SimpleNamespace(
        tools_servers=[
            _mcp_server("one", "https://mcp.example/one/sse"),
            _mcp_server("two", "https://mcp.example/two/sse"),
        ],
        tool_pool_config=None,
    )
    mcp_client = AsyncMock()
    mcp_client.get_tools.return_value = tools
    with (
        patch.object(node, "get_llm_client", return_value=MagicMock()),
        patch("apps.opspilot.metis.llm.chain.node.StructuredOutputParser"),
        patch("apps.opspilot.metis.llm.chain.node.MultiServerMCPClient", return_value=mcp_client),
    ):
        await node.setup(request)
    assert node.tool_catalog["mcp_tools"] == ["alpha", "beta"]
    assert node.tool_catalog_descriptions["mcp_tools"] == "MCP tools (2 tools from 2 servers)"
    assert [t.name for t in node._category_tool_map["mcp_tools"]] == ["alpha", "beta"]


@pytest.mark.asyncio
async def test_setup_langchain_catalog_falls_back_to_tool_description():
    """LangChain 类别：extra_tools_prompt 为空时取首个工具 description 前 100 字。"""
    node = ToolsNodes()
    long_desc = "x" * 140
    lc_tool = SimpleNamespace(name="list_pods", description=long_desc)
    request = SimpleNamespace(
        tools_servers=[
            SimpleNamespace(
                name="k8s",
                url="langchain:kubernetes",
                extra_tools_prompt="",
                extra_param_prompt="",
                enable_auth=False,
                auth_token="",
                command="",
                args=[],
                transport="",
            )
        ],
        tool_pool_config=None,
    )
    with (
        patch.object(node, "get_llm_client", return_value=MagicMock()),
        patch("apps.opspilot.metis.llm.chain.node.StructuredOutputParser"),
        patch("apps.opspilot.metis.llm.chain.node.ToolsLoader.load_tools", return_value=[lc_tool]),
    ):
        await node.setup(request)
    assert node.tool_catalog["kubernetes"] == ["list_pods"]
    assert node.tool_catalog_descriptions["kubernetes"] == long_desc[:100]


@pytest.mark.asyncio
async def test_setup_single_mcp_default_description_when_prompt_empty():
    """单 MCP 且 extra_tools_prompt 为空：描述回落到 MCP tools from {name}。"""
    node = ToolsNodes()
    mcp_tool = SimpleNamespace(name="ping", description="p")
    request = SimpleNamespace(
        tools_servers=[_mcp_server("remote", "https://mcp.example/mcp")],
        tool_pool_config=None,
    )
    mcp_client = AsyncMock()
    mcp_client.get_tools.return_value = [mcp_tool]
    with (
        patch.object(node, "get_llm_client", return_value=MagicMock()),
        patch("apps.opspilot.metis.llm.chain.node.StructuredOutputParser"),
        patch("apps.opspilot.metis.llm.chain.node.MultiServerMCPClient", return_value=mcp_client),
    ):
        await node.setup(request)
    assert node.tool_catalog_descriptions["remote"] == "MCP tools from remote"


def test_get_tools_description_prefers_all_tools_in_dynamic_mode():
    """动态模式下 self.tools 被清空，描述改从 all_tools 拼接。"""
    node = ToolsNodes()
    node.tools = []
    node.all_tools = [SimpleNamespace(name="t1", description="d1"), SimpleNamespace(name="t2", description="d2")]
    text = node.get_tools_description()
    assert "t1: d1" in text
    assert "t2: d2" in text


def test_json_to_yaml_renders_dict_list_and_scalar():
    """_json_to_yaml：dict 嵌套缩进、list 用短横线、标量直接输出。"""
    json_to_yaml = _nested_fn(ToolsNodes._build_bulk_repair_tool.__code__, "_json_to_yaml")
    text = json_to_yaml(
        {
            "spec": {
                "replicas": 3,
                "containers": [{"name": "api", "ports": [8080]}],
            }
        },
        0,
    )
    assert "spec:" in text
    assert "replicas: 3" in text
    assert "containers:" in text
    assert "- " in text
    assert "name: api" in text
    assert "ports:" in text
    assert "- 8080" in text
    assert json_to_yaml("plain", 0) == "plain"


def test_extract_patch_body_parses_single_and_double_quoted_json():
    """_extract_patch_body：单引号 / 双引号 -p JSON 转 YAML；空命令与非法 JSON 走兜底。"""
    json_to_yaml = _nested_fn(ToolsNodes._build_bulk_repair_tool.__code__, "_json_to_yaml")
    extract = _nested_fn(
        ToolsNodes._build_bulk_repair_tool.__code__,
        "_extract_patch_body",
        extra_globals={"_json_to_yaml": json_to_yaml},
    )
    assert extract("") == ""
    assert extract("kubectl scale deployment web --replicas=3") == ""

    single = extract("kubectl patch deploy a -n ns --type=strategic -p '{\"spec\":{\"replicas\":3}}'")
    assert "spec:" in single
    assert "replicas: 3" in single

    via_flag = extract("kubectl patch deploy a --patch '{\"image\":\"nginx\"}'")
    assert "image: nginx" in via_flag

    invalid = extract("kubectl patch deploy a -p '{not-json'")
    assert invalid == "{not-json"

    # 双引号包裹的非 JSON：解析失败时原样截断返回
    assert extract('kubectl patch deploy a --patch "not-json"') == "not-json"


def _patch_choice_guards():
    return (
        patch(
            "apps.opspilot.metis.llm.tools.kubernetes.user_choice_guard.build_kubernetes_cluster_choice_guard",
            return_value=None,
        ),
        patch(
            "apps.opspilot.metis.llm.tools.common.user_choice_guard.validate_user_choice_options",
            return_value="",
        ),
    )


@pytest.mark.asyncio
async def test_choice_tool_text_emits_empty_options_and_user_answer():
    """text 模式：无预设选项，用户输入原样回传。"""
    tool = ToolsNodes()._build_choice_tool()
    captured = []
    g1, g2 = _patch_choice_guards()
    with (
        g1,
        g2,
        patch("apps.opspilot.metis.llm.chain.node.dispatch_custom_event", lambda n, p, *a, **k: captured.append((n, p))),
        patch(
            "apps.opspilot.metis.llm.chain.node.wait_for_choice",
            new=AsyncMock(return_value={"selected": ["用户输入的集群名"], "source": "user"}),
        ),
    ):
        result = await tool.coroutine(question="请输入集群名", question_type="text", options=None)
    assert result == "用户回答: 用户输入的集群名。请根据用户的回答继续执行下一步操作，不要停止。"
    payload = next(p for n, p in captured if n == "user_choice_request")
    assert payload["options"] == []
    assert payload["display_hint"] == "text"
    assert payload["multiple"] is False
    assert payload["title"] == "请输入集群名"


@pytest.mark.asyncio
async def test_choice_tool_multi_select_joins_selected_labels():
    """multi_select：选项原样作为 key/label，选中项用逗号拼接。"""
    tool = ToolsNodes()._build_choice_tool()
    captured = []
    g1, g2 = _patch_choice_guards()
    with (
        g1,
        g2,
        patch("apps.opspilot.metis.llm.chain.node.dispatch_custom_event", lambda n, p, *a, **k: captured.append((n, p))),
        patch(
            "apps.opspilot.metis.llm.chain.node.wait_for_choice",
            new=AsyncMock(return_value={"selected": ["api", "web"], "source": "user"}),
        ),
    ):
        result = await tool.coroutine(question="选择工作负载", question_type="multi_select", options=["api", "web", "db"])
    assert result == "用户回答: api, web。请根据用户的回答继续执行下一步操作，不要停止。"
    payload = next(p for n, p in captured if n == "user_choice_request")
    assert payload["multiple"] is True
    assert payload["max_select"] == 3
    assert [opt["key"] for opt in payload["options"]] == ["api", "web", "db"]
    assert payload["default_keys"] == ["api"]


@pytest.mark.asyncio
async def test_choice_tool_timeout_confirm_no_swallows_dispatch_error():
    """confirm 超时选 no：dispatch 失败不阻断，返回默认否文案。"""
    tool = ToolsNodes()._build_choice_tool()
    g1, g2 = _patch_choice_guards()
    with (
        g1,
        g2,
        patch("apps.opspilot.metis.llm.chain.node.dispatch_custom_event", side_effect=RuntimeError("no graph")),
        patch(
            "apps.opspilot.metis.llm.chain.node.wait_for_choice",
            new=AsyncMock(return_value={"selected": ["no"], "source": "timeout"}),
        ),
    ):
        result = await tool.coroutine(question="确认删除？", question_type="confirm", options=None)
    assert result == "用户未在规定时间内回答，已使用默认选项: 否。请根据默认值继续操作。"
