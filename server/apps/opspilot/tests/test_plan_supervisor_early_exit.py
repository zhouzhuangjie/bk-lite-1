"""Plan-and-Execute / Supervisor：空计划、超限强制结束。"""
import asyncio
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from apps.opspilot.metis.llm.agent.plan_and_execute_agent import (
    PlanAndExecuteAgentNode,
    extract_existing_final_report,
)
from apps.opspilot.metis.llm.agent.supervisor_multi_agent import SupervisorMultiAgentNode

pytestmark = pytest.mark.unit


def test_extract_existing_final_report_finds_marker_and_skips_tool_calls():
    assert extract_existing_final_report([]) is None
    assert extract_existing_final_report([HumanMessage(content="配置问题摘要")]) is None
    tool_msg = AIMessage(content="配置问题摘要 草稿")
    tool_msg.tool_calls = [{"name": "x"}]
    assert extract_existing_final_report([tool_msg]) is None
    report = AIMessage(content="配置问题摘要：磁盘将满")
    assert extract_existing_final_report([HumanMessage(content="q"), report]) == "配置问题摘要：磁盘将满"


def test_replanner_empty_plan_and_execution_cap():
    node = PlanAndExecuteAgentNode.__new__(PlanAndExecuteAgentNode)
    empty = asyncio.run(node.replanner_node({"current_plan": []}, {}))
    assert empty == {"current_plan": []}

    capped = asyncio.run(
        node.replanner_node(
            {
                "current_plan": ["step-1"],
                "original_plan": ["step-1"],
                "execution_count": 99,
                "step_history": [],
                "messages": [],
            },
            {},
        )
    )
    assert capped == {"current_plan": []}


def test_supervisor_finishes_when_max_iterations_reached():
    node = SupervisorMultiAgentNode.__new__(SupervisorMultiAgentNode)
    request = SimpleNamespace(max_iterations=2)
    result = asyncio.run(
        node.supervisor_node(
            {"iterations": 2, "executed_agents": ["a"]},
            {"configurable": {"graph_request": request}},
        )
    )
    assert result["next_action"] == "FINISH"
    assert result["iterations"] == 3
