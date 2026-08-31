"""Supervisor 多智能体：决策解析、路由、隔离任务上下文与摘要提取。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from apps.opspilot.metis.llm.agent.supervisor_multi_agent import SupervisorMultiAgentNode

pytestmark = pytest.mark.unit


def _request(agents, user_message="查告警"):
    return SimpleNamespace(
        agents=[SimpleNamespace(name=n, description=d) for n, d in agents],
        user_message=user_message,
        supervisor_system_prompt="你是调度器",
        supervisor_context_window_size=8,
    )


def test_parse_supervisor_decision_finish_match_and_fallback():
    node = SupervisorMultiAgentNode()
    req = _request([("k8s", "集群"), ("mysql", "数据库")])
    assert node._parse_supervisor_decision("FINISH", req) == ["FINISH"]
    assert node._parse_supervisor_decision("k8s, mysql", req) == ["k8s", "mysql"]
    assert node._parse_supervisor_decision("请交给 mysql 处理", req) == ["mysql"]
    assert node._parse_supervisor_decision("???", req) == ["k8s"]


def test_should_continue_routes_finish_parallel_and_agent():
    node = SupervisorMultiAgentNode()
    assert node.should_continue({"next_action": "FINISH"}) == "FINISH"
    assert node.should_continue({"next_action": "PARALLEL"}) == "parallel_executor"
    assert node.should_continue({"next_action": "k8s"}) == "k8s"
    assert node.should_continue({}) == "FINISH"


def test_build_error_and_shared_context_result():
    node = SupervisorMultiAgentNode()
    err = node._build_error_result("k8s", "timeout", {"executed_agents": ["mysql"]})
    assert err["executed_agents"] == ["mysql", "k8s"]
    assert "timeout" in err["messages"][0].content
    msgs = [HumanMessage(content="q"), AIMessage(content="done")]
    shared = node._build_shared_context_result(msgs, "k8s", {"executed_agents": []})
    assert shared["executed_agents"] == ["k8s"]
    assert any(isinstance(m, AIMessage) for m in shared["messages"])


def test_isolated_task_context_includes_user_and_peer_summaries():
    node = SupervisorMultiAgentNode()
    req = _request([("k8s", "集群")], user_message="排查 Pod 重启")
    messages = [
        HumanMessage(content="排查 Pod 重启"),
        AIMessage(content="交给 k8s 处理节点压力"),
        AIMessage(content="[Agent: mysql]\n慢查询已排除"),
    ]
    text = node._build_isolated_task_context(messages, "k8s", req)
    assert "排查 Pod 重启" in text
    assert "交给 k8s" in text
    assert "mysql" in text
    assert "你的任务" in text


def test_extract_agent_summary_prefers_last_plain_ai():
    node = SupervisorMultiAgentNode()
    msgs = [
        AIMessage(content="中间"),
        AIMessage(content="最终结论"),
    ]
    assert node._extract_agent_summary(msgs, "k8s") == "最终结论"
    assert node._extract_agent_summary([HumanMessage(content="q")], "k8s") == "k8s 执行完成但未产生文本响应"


def test_build_supervisor_prompt_renders_agents():
    node = SupervisorMultiAgentNode()
    req = _request([("k8s", "集群")])
    state = {"executed_agents": ["mysql"], "messages": [HumanMessage(content="hello world")]}
    with patch(
        "apps.opspilot.metis.llm.agent.supervisor_multi_agent.TemplateLoader.render_template",
        return_value="PROMPT",
    ) as render:
        assert node._build_supervisor_prompt(req, state) == "PROMPT"
    data = render.call_args.args[1]
    assert "k8s" in data["agents_desc"]
    assert "mysql" in data["executed_desc"]


def test_select_context_messages_window_and_human_pair():
    node = SupervisorMultiAgentNode()
    assert node._select_context_messages([], 3) == []
    msgs = [HumanMessage(content=str(i)) for i in range(3)]
    assert node._select_context_messages(msgs, None) == msgs
    assert node._select_context_messages(msgs, 8) == msgs
    long_msgs = [
        HumanMessage(content="h0"),
        AIMessage(content="a0"),
        HumanMessage(content="h1"),
        AIMessage(content="a1"),
        AIMessage(content="a2"),
    ]
    selected = node._select_context_messages(long_msgs, 2)
    assert selected[0].content == "h1"
    assert [m.content for m in selected[-2:]] == ["a1", "a2"]


@pytest.mark.asyncio
async def test_setup_agents_builds_tools_map(monkeypatch):
    setups = []

    class FakeTools:
        def __init__(self):
            self.tools = ["t1"]

        async def setup(self, request):
            setups.append(request.system_message_prompt)

    monkeypatch.setattr("apps.opspilot.metis.llm.agent.supervisor_multi_agent.ToolsNodes", FakeTools)
    node = SupervisorMultiAgentNode()
    from apps.opspilot.metis.llm.agent.supervisor_multi_agent import AgentConfig, SupervisorMultiAgentRequest

    req = SupervisorMultiAgentRequest(
        openai_api_base="http://llm.local",
        openai_api_key="k",
        model="gpt",
        user_message="x",
        agents=[AgentConfig(name="k8s", description="集群", system_message_prompt="专属", temperature=0.1)],
    )
    await node.setup_agents(req)
    assert list(node.agent_tools_map) == ["k8s"]
    assert setups == ["专属"]
    assert node.agent_tools_map["k8s"].tools == ["t1"]
