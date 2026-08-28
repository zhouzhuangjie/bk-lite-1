"""build_react_nodes 闭包：进度事件吞错、动态目录、prepare_step 覆盖、选择续行、同批去重。"""

import json
import sys
import types
from typing import Annotated
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
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, add_messages

from apps.opspilot.metis.llm.chain.entity import (
    BasicLLMRequest,
    PrepareStepResult,
    ReflectionConfig,
    RetryConfig,
    TimeoutConfig,
)
from apps.opspilot.metis.llm.chain.node import ToolsNodes

pytestmark = pytest.mark.asyncio


@tool
def search_tool(query: str) -> str:
    """Search for info."""
    return f"found: {query}"


@tool
def analyze_deployment_configurations() -> str:
    """Return a K8s config-analysis payload with issues."""
    return json.dumps(
        {
            "cluster_name": "Kubernetes - 1",
            "problematic": 1,
            "issues_detail": [{"severity": "high", "issue": "未配置存活探针", "count": 1}],
            "_deployments_full": [
                {"name": "nginx-test", "namespace": "default", "issues": ["未配置存活探针"]},
            ],
        },
        ensure_ascii=False,
    )


class AgentState(dict):
    messages: Annotated[list, add_messages]


async def _run(
    request,
    mock_llm_responses,
    *,
    tools_list=None,
    initial_messages=None,
    additional_system_prompt=None,
    node_setup=None,
    render_side_effect=None,
    dispatch_side_effect=None,
    monotonic_side_effect=None,
):
    node_builder = ToolsNodes()
    node_builder.tools = tools_list if tools_list is not None else [search_tool]
    if node_setup:
        node_setup(node_builder)

    call_count = {"n": 0}
    responses = list(mock_llm_responses)
    llm_inputs = []
    render_calls = []

    async def mock_ainvoke(messages, *args, **kwargs):
        llm_inputs.append(list(messages))
        idx = min(call_count["n"], len(responses) - 1)
        call_count["n"] += 1
        return responses[idx]

    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_llm
    mock_llm.ainvoke = mock_ainvoke
    node_builder.get_llm_client = lambda *a, **kw: mock_llm

    graph_builder = StateGraph(AgentState)
    entry = await node_builder.build_react_nodes(
        graph_builder=graph_builder,
        composite_node_name="test_react",
        additional_system_prompt=additional_system_prompt,
    )
    graph_builder.set_entry_point(entry)
    graph = graph_builder.compile()

    def _render(template, ctx):
        render_calls.append((template, dict(ctx)))
        if render_side_effect:
            return render_side_effect(template, ctx)
        extra = ctx.get("additional_system_prompt") or ""
        dyn = ctx.get("dynamic_tool_instruction") or ""
        return f"SYS extra={extra} dyn={dyn}"

    def _dispatch(*args, **kwargs):
        if dispatch_side_effect:
            return dispatch_side_effect(*args, **kwargs)
        return None

    patches = [
        patch("apps.opspilot.metis.llm.chain.node.TemplateLoader.render_template", side_effect=_render),
        patch("apps.opspilot.metis.llm.chain.node.dispatch_custom_event", side_effect=_dispatch),
        patch(
            "apps.opspilot.metis.llm.chain.node.is_interrupt_requested_async",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "apps.opspilot.metis.llm.chain.node.wait_for_choice",
            new_callable=AsyncMock,
            return_value={"selected": ["a"], "source": "user"},
        ),
    ]
    if monotonic_side_effect is not None:
        patches.append(patch("apps.opspilot.metis.llm.chain.node.time.monotonic", side_effect=monotonic_side_effect))

    with patches[0], patches[1], patches[2], patches[3]:
        if monotonic_side_effect is not None:
            with patches[4]:
                result = await graph.ainvoke(
                    {"messages": initial_messages or [HumanMessage(content="test")]},
                    config={"configurable": {"graph_request": request, "trace_id": "test", "execution_id": "exec-1"}},
                )
        else:
            result = await graph.ainvoke(
                {"messages": initial_messages or [HumanMessage(content="test")]},
                config={"configurable": {"graph_request": request, "trace_id": "test", "execution_id": "exec-1"}},
            )

    return result.get("messages", []), call_count["n"], llm_inputs, render_calls


def _base_request(**kwargs):
    defaults = dict(
        max_steps=8,
        compaction_enabled=False,
        retry_config=RetryConfig(enabled=False),
        reflection_config=ReflectionConfig(enabled=False),
        timeout_config=TimeoutConfig(enabled=False),
    )
    defaults.update(kwargs)
    return BasicLLMRequest(**defaults)


def _joined(messages):
    return "\n".join(str(getattr(m, "content", "")) for m in messages)


async def test_dispatch_custom_event_exception_is_swallowed():
    def boom(*_a, **_k):
        raise RuntimeError("event bus down")

    messages, llm_calls, _, _ = await _run(
        _base_request(),
        [AIMessage(content="纯文本结束")],
        dispatch_side_effect=boom,
    )
    assert llm_calls == 1
    assert any("纯文本结束" in str(getattr(m, "content", "")) for m in messages)


async def test_dynamic_mode_injects_catalog_into_system_prompt():
    def setup(builder):
        builder._dynamic_mode = True
        builder.tool_catalog = {"mysql": ["get_database_metrics"]}
        builder.tool_catalog_descriptions = {"mysql": "MySQL 监控"}
        builder._category_tool_map = {"mysql": []}
        builder.active_tools = []

    _, _, _, renders = await _run(
        _base_request(),
        [AIMessage(content="先激活工具")],
        node_setup=setup,
    )
    dyn_texts = [ctx.get("dynamic_tool_instruction", "") for _, ctx in renders]
    assert any("mysql" in text and "MySQL 监控" in text and "activate_tools" in text for text in dyn_texts)


async def test_prepare_step_additional_system_prompt_overrides_and_prepends():
    def hook(ctx):
        return PrepareStepResult(
            additional_system_prompt="OVERRIDE-PROMPT-XYZ",
            messages=[HumanMessage(content="only-human")],
        )

    _, _, llm_inputs, renders = await _run(
        _base_request(prepare_step_hooks=[hook]),
        [AIMessage(content="ok")],
        additional_system_prompt="BASE-PROMPT",
    )
    extras = [ctx.get("additional_system_prompt") for _, ctx in renders]
    assert "BASE-PROMPT" in extras
    assert "OVERRIDE-PROMPT-XYZ" in extras
    first_llm = llm_inputs[0]
    assert isinstance(first_llm[0], SystemMessage)
    assert "OVERRIDE-PROMPT-XYZ" in str(first_llm[0].content)
    assert any(getattr(m, "content", "") == "only-human" for m in first_llm)


def _choice_history(question, answer, extra_before=None):
    history = list(extra_before or [])
    history.extend(
        [
            HumanMessage(content="检查集群"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "request_user_choice",
                        "args": {"question": question, "title": question},
                        "id": "c1",
                    }
                ],
            ),
            ToolMessage(content=answer, name="request_user_choice", tool_call_id="c1"),
        ]
    )
    return history


async def test_choice_continuation_user_declined():
    _, _, llm_inputs, _ = await _run(
        _base_request(),
        [AIMessage(content="好的，稍后处理。")],
        initial_messages=_choice_history("是否继续修复？", "稍后处理"),
    )
    assert "不需要进一步操作" in _joined(llm_inputs[0])


async def test_choice_continuation_group_by_target_and_category_and_all():
    cases = [
        ("按工作负载展示", "group_by='target'"),
        ("按类别聚合", "group_by='category'"),
        ("全部一次性展示", "group_by='all'"),
    ]
    for answer, expected in cases:
        _, _, llm_inputs, _ = await _run(
            _base_request(),
            [AIMessage(content="收到")],
            initial_messages=_choice_history("请选择修复展示方式", answer),
        )
        joined = _joined(llm_inputs[0])
        assert expected in joined, (answer, joined)


async def test_choice_continuation_report_already_exists_asks_for_commands():
    extra = [ToolMessage(content="report-done", name="generate_repair_report", tool_call_id="r0")]
    extra.extend(HumanMessage(content=f"pad-{i}") for i in range(20))
    _, _, llm_inputs, _ = await _run(
        _base_request(),
        [AIMessage(content="kubectl patch ...")],
        initial_messages=_choice_history("是否实施修复命令？", "是", extra_before=extra),
    )
    joined = _joined(llm_inputs[0])
    assert "修复报告已经展示过了" in joined
    assert "不要调用任何工具" in joined


async def test_duplicate_tool_calls_in_same_batch_are_deduped():
    request = _base_request(
        reflection_config=ReflectionConfig(enabled=False, duplicate_call_hard_enabled=True),
    )
    dup = AIMessage(
        content="",
        tool_calls=[
            {"name": "search_tool", "args": {"query": "same"}, "id": "t1"},
            {"name": "search_tool", "args": {"query": "same"}, "id": "t2"},
        ],
    )
    messages, llm_calls, _, _ = await _run(
        request,
        [dup, AIMessage(content="done")],
    )
    search_tool_msgs = [m for m in messages if getattr(m, "name", "") == "search_tool"]
    assert len(search_tool_msgs) == 1
    assert llm_calls >= 1


async def test_frozen_tool_calls_assignment_falls_back_to_object_setattr():
    class FrozenAIMessage(AIMessage):
        def __setattr__(self, name, value):
            if name == "tool_calls" and "content" in self.__dict__:
                raise RuntimeError("frozen tool_calls")
            return super().__setattr__(name, value)

    frozen = FrozenAIMessage(
        content="",
        tool_calls=[
            {"name": "search_tool", "args": {"query": "same"}, "id": "t1"},
            {"name": "search_tool", "args": {"query": "same"}, "id": "t2"},
        ],
    )
    request = _base_request(
        reflection_config=ReflectionConfig(enabled=False, duplicate_call_hard_enabled=True),
    )
    messages, _, _, _ = await _run(request, [frozen, AIMessage(content="done")])
    search_tool_msgs = [m for m in messages if getattr(m, "name", "") == "search_tool"]
    assert len(search_tool_msgs) == 1


async def test_k8s_analysis_loop_clears_choice_and_returns_done_message():
    responses = [
        AIMessage(
            content="分析配置",
            tool_calls=[{"name": "analyze_deployment_configurations", "args": {}, "id": "a1"}],
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "request_user_choice",
                    "args": {"question": "请选择修复展示方式", "options": []},
                    "id": "c2",
                }
            ],
        ),
        AIMessage(content="should-not-run"),
    ]
    messages, llm_calls, _, _ = await _run(
        _base_request(),
        responses,
        tools_list=[analyze_deployment_configurations],
    )
    assert llm_calls == 2
    last = str(getattr(messages[-1], "content", ""))
    assert "基础配置检查" in last or "未启用" in last or "工作负载" in last
    assert not any(tc.get("name") == "request_user_choice" for m in messages for tc in (getattr(m, "tool_calls", None) or []))


async def test_choice_and_repair_report_concurrent_calls_drop_report():
    responses = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "request_user_choice",
                    "args": {"question": "请选择修复展示方式"},
                    "id": "c1",
                },
                {"name": "generate_repair_report", "args": {"group_by": "all"}, "id": "r1"},
            ],
        ),
        AIMessage(content="等待选择"),
    ]
    messages, _, _, _ = await _run(
        _base_request(),
        responses,
        tools_list=[analyze_deployment_configurations],
    )
    first_ai = next(m for m in messages if getattr(m, "type", "") == "ai" and getattr(m, "tool_calls", None))
    names = [tc.get("name") for tc in (first_ai.tool_calls or [])]
    assert "request_user_choice" in names
    assert "generate_repair_report" not in names


async def test_total_timeout_on_second_step_uses_elapsed_branch():
    clock = {"n": 0}

    def fake_monotonic():
        clock["n"] += 1
        return 1000.0 + clock["n"] * 10.0

    request = _base_request(
        timeout_config=TimeoutConfig(enabled=True, total_timeout_seconds=5.0, step_timeout_seconds=0, llm_timeout_seconds=0),
    )
    responses = [
        AIMessage(content="s1", tool_calls=[{"name": "search_tool", "args": {"query": "x"}, "id": "c1"}]),
        AIMessage(content="should-not"),
    ]
    messages, llm_calls, _, _ = await _run(
        request,
        responses,
        monotonic_side_effect=fake_monotonic,
    )
    assert llm_calls == 1
    assert any("超时" in str(getattr(m, "content", "")) for m in messages)
