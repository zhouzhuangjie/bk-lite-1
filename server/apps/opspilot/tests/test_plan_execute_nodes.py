"""Plan-and-Execute：planner / executor / replanner / summary 节点契约。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from apps.opspilot.metis.llm.agent.plan_and_execute_agent import (
    Plan,
    PlanAndExecuteAgentNode,
    PlanResponse,
    ReplanResponse,
)

pytestmark = pytest.mark.unit


def _config(user_message="排查 Pod"):
    return {"configurable": {"graph_request": SimpleNamespace(user_message=user_message)}}


def _node():
    node = PlanAndExecuteAgentNode()
    node.structured_output_parser = MagicMock()
    return node


@pytest.mark.asyncio
async def test_planner_node_writes_plan_steps(monkeypatch):
    node = _node()
    node.structured_output_parser.parse_with_structured_output = AsyncMock(
        return_value=PlanResponse(plan=Plan(steps=["查节点", "查事件"]), reasoning="先定位")
    )
    monkeypatch.setattr(
        "apps.opspilot.metis.llm.agent.plan_and_execute_agent.TemplateLoader.render_template",
        lambda *a, **k: "planning",
    )
    out = await node.planner_node({}, _config())
    assert out["original_plan"] == ["查节点", "查事件"]
    assert out["current_plan"] == ["查节点", "查事件"]
    assert out["execution_count"] == 0
    assert "执行计划已制定" in out["messages"][0].content
    assert "先定位" in out["messages"][0].content


@pytest.mark.asyncio
async def test_executor_node_empty_plan_passthrough_and_injects_step(monkeypatch):
    node = _node()
    empty = await node.executor_node({"current_plan": [], "execution_count": 0}, _config())
    assert empty["current_plan"] == []

    monkeypatch.setattr(
        "apps.opspilot.metis.llm.agent.plan_and_execute_agent.TemplateLoader.render_template",
        lambda *a, **k: "执行：查节点",
    )
    out = await node.executor_node(
        {"current_plan": ["查节点", "查事件"], "execution_count": 0, "step_history": []},
        _config(),
    )
    assert out["execution_count"] == 1
    assert out["step_history"] == ["[步骤 1] 执行: 查节点"]
    assert out["execution_prompt"] == "执行：查节点"
    assert isinstance(out["messages"][0], HumanMessage)
    assert out["messages"][0].content == "执行：查节点"


@pytest.mark.asyncio
async def test_replanner_empty_cap_complete_adjust_and_silent(monkeypatch):
    node = _node()
    empty = await node.replanner_node({"current_plan": [], "original_plan": ["a"]}, _config())
    assert empty == {"current_plan": []}

    capped = await node.replanner_node(
        {"current_plan": ["a"], "original_plan": ["a"], "execution_count": 20, "step_history": [], "messages": []},
        _config(),
    )
    assert capped == {"current_plan": []}

    monkeypatch.setattr(
        "apps.opspilot.metis.llm.agent.plan_and_execute_agent.TemplateLoader.render_template",
        lambda *a, **k: "replan",
    )
    node.structured_output_parser.parse_with_structured_output = AsyncMock(
        return_value=ReplanResponse(updated_plan=Plan(steps=[]), reasoning="完成", is_complete=True)
    )
    done = await node.replanner_node(
        {
            "current_plan": ["查事件"],
            "original_plan": ["查节点", "查事件"],
            "execution_count": 1,
            "step_history": ["s1"],
            "messages": [AIMessage(content="节点正常")],
        },
        _config(),
    )
    assert done == {"current_plan": []}

    node.structured_output_parser.parse_with_structured_output = AsyncMock(
        return_value=ReplanResponse(updated_plan=Plan(steps=["改查日志"]), reasoning="调整", is_complete=False)
    )
    adjusted = await node.replanner_node(
        {
            "current_plan": ["查事件"],
            "original_plan": ["查节点", "查事件"],
            "execution_count": 1,
            "step_history": ["s1"],
            "messages": [AIMessage(content="节点正常")],
        },
        _config(),
    )
    assert adjusted["current_plan"] == ["改查日志"]
    assert "计划已调整" in adjusted["messages"][0].content
    assert "调整" in adjusted["messages"][0].content

    node.structured_output_parser.parse_with_structured_output = AsyncMock(
        return_value=ReplanResponse(updated_plan=Plan(steps=["查事件"]), reasoning="不变", is_complete=False)
    )
    silent = await node.replanner_node(
        {
            "current_plan": ["查节点", "查事件"],
            "original_plan": ["查节点", "查事件"],
            "execution_count": 1,
            "step_history": ["s1"],
            "messages": [AIMessage(content="ok")],
        },
        _config(),
    )
    assert silent == {"current_plan": ["查事件"]}


@pytest.mark.asyncio
async def test_should_continue_and_summary_reuses_existing():
    node = _node()
    assert await node.should_continue({"current_plan": []}) == "summary"
    assert await node.should_continue({"current_plan": ["下一步"]}) == "executor"

    reused = await node.summary_node(
        {"final_response": "已有总结", "original_plan": ["a"], "messages": []},
        _config(),
    )
    assert reused["final_response"] == "已有总结"

    report = "配置问题摘要：CPU 超限"
    from_report = await node.summary_node(
        {
            "final_response": None,
            "original_plan": ["a"],
            "messages": [AIMessage(content=report)],
        },
        _config(),
    )
    assert from_report["final_response"] == report
    assert from_report["messages"][0].content == report
