"""ToolsNodes.build_deepagent_nodes：空结果、无新消息、只返回增量消息。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from apps.opspilot.metis.llm.chain.node import ToolsNodes

pytestmark = pytest.mark.unit


class _GraphBuilder:
    def __init__(self):
        self.nodes = {}

    def add_node(self, name, fn):
        self.nodes[name] = fn


@pytest.mark.asyncio
async def test_deepagent_wrapper_empty_no_new_and_incremental(monkeypatch):
    builder = _GraphBuilder()
    node = ToolsNodes()
    node.tools = ["k8s"]
    monkeypatch.setattr(node, "get_llm_client", lambda req: "llm")
    monkeypatch.setattr(
        "apps.opspilot.metis.llm.chain.node.TemplateLoader.render_template",
        lambda *a, **k: "sys",
    )
    deep = MagicMock()
    monkeypatch.setattr("apps.opspilot.metis.llm.chain.node.create_deep_agent", lambda **k: deep)

    name = await node.build_deepagent_nodes(builder, composite_node_name="deep", additional_system_prompt="extra")
    assert name == "deep_wrapper"
    wrapper = builder.nodes["deep_wrapper"]
    config = {"configurable": {"graph_request": SimpleNamespace(system_message_prompt="user-sys")}}
    incoming = [HumanMessage(content="q")]

    deep.ainvoke = AsyncMock(return_value={"messages": []})
    empty = await wrapper({"messages": incoming}, config)
    assert empty["messages"][0].content == "DeepAgent 未返回任何消息"

    deep.ainvoke = AsyncMock(return_value={"messages": incoming})
    nonew = await wrapper({"messages": incoming}, config)
    assert nonew["messages"][0].content == "DeepAgent 未产生新的响应"

    new_msg = AIMessage(content="done")
    deep.ainvoke = AsyncMock(return_value={"messages": incoming + [new_msg]})
    ok = await wrapper({"messages": incoming}, config)
    assert ok["messages"] == [new_msg]
    assert deep.ainvoke.call_args.kwargs["config"]["recursion_limit"] == 100
