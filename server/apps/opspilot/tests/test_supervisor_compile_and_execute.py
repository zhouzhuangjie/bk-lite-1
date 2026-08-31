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


class _TempGraph:
    def __init__(self, result_factory):
        self._result_factory = result_factory

    def set_entry_point(self, name):
        self.entry = name

    def compile(self):
        factory = self._result_factory

        class Compiled:
            async def ainvoke(self, state, config):
                return factory(state)

        return Compiled()


@pytest.mark.asyncio
async def test_execute_agent_isolation_shared_and_empty_results(monkeypatch):
    node = SupervisorMultiAgentNode()

    class FakeTools:
        async def build_react_nodes(self, **kwargs):
            assert kwargs["composite_node_name"] == "k8s_react"
            return "entry"

    node.agent_tools_map["k8s"] = FakeTools()

    def isolation_result(state):
        return {"messages": state["messages"] + [AIMessage(content="集群正常")]}

    monkeypatch.setattr(
        "apps.opspilot.metis.llm.agent.supervisor_multi_agent.StateGraph",
        lambda *_a, **_k: _TempGraph(isolation_result),
    )
    isolated = await node.agent_executor_node("k8s")
    out = await isolated(
        {"messages": [HumanMessage(content="查 Pod")], "executed_agents": []},
        {"configurable": {"graph_request": _request()}},
    )
    assert out["active_agent"] == "k8s"
    assert out["executed_agents"] == ["k8s"]
    assert out["messages"][0].content.startswith("[Agent: k8s]")
    assert "集群正常" in out["messages"][0].content

    def echo_input(state):
        return {"messages": state["messages"]}

    monkeypatch.setattr(
        "apps.opspilot.metis.llm.agent.supervisor_multi_agent.StateGraph",
        lambda *_a, **_k: _TempGraph(echo_input),
    )
    no_new = await isolated(
        {"messages": [HumanMessage(content="查 Pod")], "executed_agents": ["mysql"]},
        {"configurable": {"graph_request": _request()}},
    )
    assert "未产生新的响应" in no_new["messages"][0].content
    assert no_new["executed_agents"] == ["mysql", "k8s"]

    def empty_result(_state):
        return {"messages": []}

    monkeypatch.setattr(
        "apps.opspilot.metis.llm.agent.supervisor_multi_agent.StateGraph",
        lambda *_a, **_k: _TempGraph(empty_result),
    )
    empty = await isolated(
        {"messages": [HumanMessage(content="q")], "executed_agents": []},
        {"configurable": {"graph_request": _request()}},
    )
    assert "未产生有效响应" in empty["messages"][0].content

    def shared_result(state):
        return {"messages": state["messages"] + [AIMessage(content="共享结论")]}

    monkeypatch.setattr(
        "apps.opspilot.metis.llm.agent.supervisor_multi_agent.StateGraph",
        lambda *_a, **_k: _TempGraph(shared_result),
    )
    shared_req = _request(agents=[AgentConfig(name="k8s", description="集群", context_isolation=False)])
    shared = await isolated(
        {"messages": [HumanMessage(content="q")], "executed_agents": []},
        {"configurable": {"graph_request": shared_req}},
    )
    assert any(isinstance(m, AIMessage) and "共享结论" in m.content for m in shared["messages"])
    assert shared["executed_agents"] == ["k8s"]


@pytest.mark.asyncio
async def test_parallel_executor_merges_success_and_exception():
    node = SupervisorMultiAgentNode()

    async def ok_exec(state, config):
        return {"messages": [AIMessage(content="[Agent: k8s]\nok")], "executed_agents": ["k8s"]}

    async def boom_exec(state, config):
        raise RuntimeError("timeout")

    async def fake_executor(name):
        return ok_exec if name == "k8s" else boom_exec

    node.agent_executor_node = fake_executor
    out = await node.parallel_executor_node(
        {"parallel_agents": ["k8s", "mysql"], "executed_agents": ["prior"], "messages": []},
        {"configurable": {"graph_request": _request(agents=[_agent(), _agent("mysql", "库")])}},
    )
    texts = [m.content for m in out["messages"]]
    assert "[Agent: k8s]\nok" in texts
    assert any("mysql" in t and "timeout" in t for t in texts)
    assert "k8s" in out["executed_agents"]
    assert "mysql" in out["executed_agents"]
    assert "prior" in out["executed_agents"]

    empty = await node.parallel_executor_node({"parallel_agents": [], "executed_agents": ["x"]}, {})
    assert empty == {"messages": [], "executed_agents": ["x"]}

