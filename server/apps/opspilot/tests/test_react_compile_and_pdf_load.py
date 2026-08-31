"""ReAct 候选生成降级、LATS/Plan 图编译接线、PDF load 模式。"""
import sys
import types
from types import SimpleNamespace

import pydantic.root_model  # noqa
import pytest
from langchain_core.messages import AIMessage, HumanMessage

for _mod_name in ("oracledb", "pyodbc"):
    sys.modules.setdefault(_mod_name, types.ModuleType(_mod_name))
_falkordb = types.ModuleType("falkordb")
_falkordb.Graph = type("Graph", (), {})
sys.modules.setdefault("falkordb", _falkordb)
_falkordb_asyncio = types.ModuleType("falkordb.asyncio")
_falkordb_asyncio.FalkorDB = type("FalkorDB", (), {})
sys.modules.setdefault("falkordb.asyncio", _falkordb_asyncio)

from langgraph.constants import END  # noqa: E402
from apps.opspilot.metis.llm.agent.lats_agent import LatsAgentGraph, LatsAgentRequest  # noqa: E402
from apps.opspilot.metis.llm.agent.plan_and_execute_agent import (  # noqa: E402
    PlanAndExecuteAgentGraph,
    PlanAndExecuteAgentRequest,
)
from apps.opspilot.metis.llm.chain.node import ToolsNodes  # noqa: E402
from apps.opspilot.metis.llm.loader.pdf_loader import PDFLoader  # noqa: E402


@pytest.mark.asyncio
async def test_invoke_react_for_candidate_returns_last_ai_and_fallbacks(monkeypatch):
    nodes = ToolsNodes.__new__(ToolsNodes)

    class FakeBuilder:
        def __init__(self, *_a, **_k):
            pass

        def set_entry_point(self, name):
            self.entry = name

        def compile(self):
            class Compiled:
                async def ainvoke(self, state, config):
                    return {"messages": [HumanMessage(content="h"), AIMessage(content="候选")]}

            return Compiled()

    async def _build(*_a, **_k):
        return "entry"

    nodes.build_react_nodes = _build
    monkeypatch.setattr("apps.opspilot.metis.llm.chain.node.StateGraph", FakeBuilder)
    msg = await nodes.invoke_react_for_candidate("如何修", [HumanMessage(content="u")], {}, "sys")
    assert msg.content == "候选"

    class EmptyBuilder(FakeBuilder):
        def compile(self):
            class Compiled:
                async def ainvoke(self, state, config):
                    return {"messages": [HumanMessage(content="only-human")]}

            return Compiled()

    monkeypatch.setattr("apps.opspilot.metis.llm.chain.node.StateGraph", EmptyBuilder)
    fallback = await nodes.invoke_react_for_candidate("如何修", [], {}, "sys")
    assert fallback.content == "正在分析问题: 如何修"

    async def _boom(*_a, **_k):
        raise RuntimeError("graph down")

    nodes.build_react_nodes = _boom
    degraded = await nodes.invoke_react_for_candidate("如何修", [], {}, "sys")
    assert "重新分析这个问题: 如何修" in degraded.content
    assert degraded.tool_calls == []


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


@pytest.mark.asyncio
async def test_lats_compile_graph_wires_search_nodes(monkeypatch):
    fake = _FakeGraph()

    class FakeNode:
        generate_initial_response = object()
        expand = object()
        generate_final_answer = object()
        should_continue = object()

        async def setup(self, request):
            assert request.user_message == "q"

    monkeypatch.setattr("apps.opspilot.metis.llm.agent.lats_agent.LatsAgentNode", lambda: FakeNode())
    monkeypatch.setattr("apps.opspilot.metis.llm.agent.lats_agent.StateGraph", lambda *_a, **_k: fake)
    graph = LatsAgentGraph()
    monkeypatch.setattr(graph, "prepare_graph", lambda gb, nb: "last")
    out = await graph.compile_graph(LatsAgentRequest(user_message="q"))
    assert out is fake.compiled
    assert fake.nodes == ["generate_initial_response", "expand", "generate_final_answer"]
    assert ("last", "generate_initial_response") in fake.edges
    assert ("generate_final_answer", END) in fake.edges
    assert fake.cond[0][0] == "generate_initial_response"
    assert fake.cond[1][0] == "expand"


@pytest.mark.asyncio
async def test_plan_and_execute_compile_graph_wires_planner(monkeypatch):
    fake = _FakeGraph()

    class FakeNode:
        planner_node = object()
        executor_node = object()
        replanner_node = object()
        summary_node = object()
        should_continue = object()

        async def setup(self, request):
            return None

        async def build_react_nodes(self, **kwargs):
            assert kwargs["next_node"] == "replanner"
            fake.add_node("react_step_executor_wrapper", object())

    monkeypatch.setattr(
        "apps.opspilot.metis.llm.agent.plan_and_execute_agent.PlanAndExecuteAgentNode",
        lambda: FakeNode(),
    )
    monkeypatch.setattr("apps.opspilot.metis.llm.agent.plan_and_execute_agent.StateGraph", lambda *_a, **_k: fake)
    graph = PlanAndExecuteAgentGraph()
    monkeypatch.setattr(graph, "prepare_graph", lambda gb, nb: "last")
    out = await graph.compile_graph(PlanAndExecuteAgentRequest(user_message="plan"))
    assert out is fake.compiled
    assert "planner" in fake.nodes
    assert "executor" in fake.nodes
    assert ("last", "planner") in fake.edges
    assert ("planner", "executor") in fake.edges


def test_pdf_loader_load_full_and_page_modes(monkeypatch):
    page = SimpleNamespace(number=0)

    class FakePdf(list):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    fake_pdf = FakePdf([page])
    monkeypatch.setattr("apps.opspilot.metis.llm.loader.pdf_loader.fitz.open", lambda *_a, **_k: fake_pdf)
    monkeypatch.setattr("apps.opspilot.metis.llm.loader.pdf_loader.tqdm", lambda it, **k: it)

    full = PDFLoader("/tmp/a.pdf", ocr=None, load_mode="full")
    monkeypatch.setattr(full, "_parse_images", lambda pdf: [])
    monkeypatch.setattr(full, "_get_table_areas", lambda pdf: [])
    monkeypatch.setattr(full, "_extract_page_text", lambda page, areas: "hello page")
    monkeypatch.setattr(full, "_parse_tables", lambda: [])
    docs = full.load()
    assert len(docs) == 1
    assert docs[0].page_content == "hello page"

    paged = PDFLoader("/tmp/a.pdf", ocr=None, load_mode="page")
    monkeypatch.setattr(paged, "_parse_images", lambda pdf: [])
    monkeypatch.setattr(paged, "_get_table_areas", lambda pdf: [])
    monkeypatch.setattr(paged, "_extract_page_text", lambda page, areas: "page-text")
    monkeypatch.setattr(paged, "_parse_tables", lambda: [])
    page_docs = paged.load()
    assert len(page_docs) == 1
    assert page_docs[0].metadata["page"] == 1
    assert page_docs[0].page_content == "page-text"
