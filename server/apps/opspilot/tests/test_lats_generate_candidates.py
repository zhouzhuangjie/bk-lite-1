"""LATS 候选并行生成：按 search_config.max_candidates 调用 ReAct。"""
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from apps.opspilot.metis.llm.agent.lats_agent import LatsAgentNode

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_generate_candidates_runs_configured_count(monkeypatch):
    node = LatsAgentNode()
    calls = []

    async def fake_invoke(user_message, messages, config, system_message):
        calls.append((user_message, system_message, len(messages)))
        return AIMessage(content=f"候选{len(calls)}")

    node.invoke_react_for_candidate = fake_invoke
    monkeypatch.setattr(
        "apps.opspilot.metis.llm.agent.lats_agent.TemplateLoader.render_template",
        lambda *_a, **_k: "candidate-sys",
    )
    cfg = SimpleNamespace(max_candidates=2)
    out = await node._generate_candidates(
        "如何修 Pod",
        [HumanMessage(content="上下文")],
        {"configurable": {"search_config": cfg}},
    )
    assert [m.content for m in out] == ["候选1", "候选2"]
    assert len(calls) == 2
    assert calls[0][0] == "如何修 Pod"
    assert calls[0][1] == "candidate-sys"
    assert calls[0][2] == 1
