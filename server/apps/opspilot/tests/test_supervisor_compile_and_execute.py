"""Supervisor 图编译接线、子 Agent 缺配置/未初始化、决策节点与终答提取。"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from apps.opspilot.metis.llm.agent.supervisor_multi_agent import (
    AgentConfig,
    SupervisorMultiAgentGraph,
    SupervisorMultiAgentNode,
    SupervisorMultiAgentRequest,
)

pytestmark = pytest.mark.unit


class _FakeGraph:
    def __init__(self):
        self.nodes = []
        self.edges = []
        self.cond = []
        self.compiled = object()

    def add_node(self, name, fn):
        self.nodes.append(name)

    def add_edge(self, src, dst):
        self.edges.append((src, dst))

    def add_conditional_edges(self, src, fn, mapping):
        self.cond.append((src, tuple(mapping.keys())))

    def compile(self):
        return self.compiled


def _agent(name="k8s", description="集群"):
    return AgentConfig(name=name, description=description)


def _request(agents=None, user_message="查告警", **kwargs):
    return SupervisorMultiAgentRequest(
        user_message=user_message,
        agents=agents if agents is not None else [_agent()],
        **kwargs,
    )


@pytest.mark.asyncio
async def test_compile_graph_wires_supervisor_agents_and_parallel(monkeypatch):
    fake = _FakeGraph()

    class FakeNode:
        supervisor_node = object()
        parallel_executor_node = object()
        should_continue = object()

        async def setup_supervisor(self, request):
            assert request.user_message == "查告警"

        async def setup_agents(self, request):
            assert [a.name for a in request.agents] == ["k8s", "mysql"]

        async def agent_executor_node(self, name):
            return f"exec-{name}"

    monkeypatch.setattr(
        "apps.opspilot.metis.llm.agent.supervisor_multi_agent.SupervisorMultiAgentNode",
        lambda: FakeNode(),
    )
    monkeypatch.setattr(
        "apps.opspilot.metis.llm.agent.supervisor_multi_agent.StateGraph",
        lambda *_a, **_k: fake,
    )
    graph = SupervisorMultiAgentGraph()
    monkeypatch.setattr(graph, "prepare_graph", lambda gb, nb: "last")
    out = await graph.compile_graph(_request(agents=[_agent(), _agent("mysql", "库")]))
    assert out is fake.compiled
    assert fake.nodes == ["supervisor", "k8s", "mysql", "parallel_executor"]
    assert ("last", "supervisor") in fake.edges
    assert ("k8s", "supervisor") in fake.edges
    assert ("mysql", "supervisor") in fake.edges
    assert ("parallel_executor", "supervisor") in fake.edges
    assert fake.cond[0][0] == "supervisor"
    assert set(fake.cond[0][1]) == {"k8s", "mysql", "FINISH", "parallel_executor"}


@pytest.mark.asyncio
async def test_execute_agent_missing_config_and_uninitialized():
    node = SupervisorMultiAgentNode()
    missing = await node.agent_executor_node("ghost")
    missing_out = await missing(
        {"executed_agents": ["mysql"], "messages": []},
        {"configurable": {"graph_request": _request()}},
    )
    assert missing_out["executed_agents"] == ["mysql", "ghost"]
    assert "未找到 Agent ghost" in missing_out["messages"][0].content

    uninit = await node.agent_executor_node("k8s")
    uninit_out = await uninit(
        {"executed_agents": [], "messages": []},
        {"configurable": {"graph_request": _request()}},
    )
    assert uninit_out["executed_agents"] == ["k8s"]
    assert "Agent k8s 未初始化" in uninit_out["messages"][0].content


@pytest.mark.asyncio
async def test_supervisor_node_max_iterations_and_llm_routes(monkeypatch):
    node = SupervisorMultiAgentNode()
    req = _request(max_iterations=1)
    capped = await node.supervisor_node(
        {"iterations": 1, "executed_agents": ["k8s"], "messages": []},
        {"configurable": {"graph_request": req}},
    )
    assert capped["next_action"] == "FINISH"
    assert capped["iterations"] == 2

    llm = MagicMock()
    llm.invoke.return_value = AIMessage(content="k8s")
    monkeypatch.setattr(node, "get_llm_client", lambda *a, **k: llm)
    monkeypatch.setattr(
        "apps.opspilot.metis.llm.agent.supervisor_multi_agent.TemplateLoader.render_template",
        lambda *a, **k: "prompt",
    )
    routed = await node.supervisor_node(
        {"iterations": 0, "executed_agents": [], "messages": [HumanMessage(content="q")]},
        {"configurable": {"graph_request": _request(agents=[_agent(), _agent("mysql", "库")])}},
    )
    assert routed["next_action"] == "k8s"
    assert routed["parallel_agents"] == []
    assert routed["iterations"] == 1

    llm.invoke.return_value = AIMessage(content="k8s, mysql")
    parallel = await node.supervisor_node(
        {"iterations": 0, "executed_agents": [], "messages": [HumanMessage(content="q")]},
        {"configurable": {"graph_request": _request(agents=[_agent(), _agent("mysql", "库")])}},
    )
    assert parallel["next_action"] == "PARALLEL"
    assert parallel["parallel_agents"] == ["k8s", "mysql"]

    llm.invoke.return_value = AIMessage(content="FINISH")
    finished = await node.supervisor_node(
        {"iterations": 0, "executed_agents": ["k8s"], "messages": [HumanMessage(content="q")]},
        {"configurable": {"graph_request": req}},
    )
    assert finished["next_action"] == "FINISH"


@pytest.mark.asyncio
async def test_execute_extracts_last_message_and_tokens(monkeypatch):
    graph = SupervisorMultiAgentGraph()
    compiled = object()
    monkeypatch.setattr(graph, "compile_graph", AsyncMock(return_value=compiled))

    async def _invoke(compiled_graph, request):
        assert compiled_graph is compiled
        return {
            "messages": [
                HumanMessage(content="q"),
                AIMessage(
                    content="最终结论",
                    response_metadata={"token_usage": {"prompt_tokens": 3, "completion_tokens": 5}},
                ),
            ],
            "executed_agents": ["k8s"],
            "iterations": 2,
        }

    monkeypatch.setattr(graph, "invoke", _invoke)
    resp = await graph.execute(_request(output_mode="last_message"))
    assert resp.message == "最终结论"
    assert resp.prompt_tokens == 3
    assert resp.completion_tokens == 5
    assert resp.total_tokens == 8
    assert resp.executed_agents == ["k8s"]
    assert resp.iterations == 2


def test_extract_final_message_modes():
    graph = SupervisorMultiAgentGraph()
    empty = graph._extract_final_message({"messages": []}, "last_message")
    assert empty == "未生成任何响应"
    no_ai = graph._extract_final_message({"messages": [HumanMessage(content="q")]}, "last_message")
    assert no_ai == "未找到有效的 AI 响应"
    last = graph._extract_final_message(
        {"messages": [AIMessage(content="a"), AIMessage(content="b")]},
        "last_message",
    )
    assert last == "b"
    full = graph._extract_final_message(
        {"messages": [AIMessage(content="a"), HumanMessage(content="q"), AIMessage(content="b")]},
        "full_history",
    )
    assert full == "a\n\n---\n\n" + "b"
    unknown = graph._extract_final_message({"messages": [AIMessage(content="a")]}, "other")
    assert unknown == "未知的 output_mode"
