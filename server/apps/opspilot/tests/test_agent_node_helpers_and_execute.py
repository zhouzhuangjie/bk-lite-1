"""AgentNode：文件注入、记忆截断、触发类型、execute/sse/agui 成功与失败。"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from django.core.files.storage import FileSystemStorage

from apps.core.utils.safe_template import TemplateSecurityError
from apps.opspilot.models.knowledge_mgmt import FileKnowledge as FileKnowledgeModel
from apps.opspilot.services.builtin_tools import BUILTIN_ATTACHMENT_FILE_TOOL_NAME
from apps.opspilot.services.chat_service import ChatService
from apps.opspilot.services.workflow_attachment_service import create_workflow_attachment_asset
from apps.opspilot.utils.chat_flow_utils.engine.core.variable_manager import VariableManager
from apps.opspilot.utils.chat_flow_utils.nodes.agent.agent import AgentNode, AgentsNode

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _local_file_storage(tmp_path):
    field = FileKnowledgeModel._meta.get_field("file")
    previous = field.storage
    field.storage = FileSystemStorage(location=str(tmp_path))
    yield
    field.storage = previous


def _node(extra=None):
    vm = VariableManager()
    vm.set_variable("flow_input", {"user_id": "u1", "locale": "zh", "execution_id": "exec-1"})
    vm.set_variable("flow_id", "flow-1")
    vm.set_variable("current_node_id", "agent-1")
    if extra:
        for key, value in extra.items():
            vm.set_variable(key, value)
    return AgentNode(vm)


def test_process_uploaded_files_and_render_prompt_paths():
    node = _node()
    assert node._process_uploaded_files(None) == ""
    assert node._process_uploaded_files([{"name": "a.txt"}]) == ""
    out = node._process_uploaded_files([{"name": "a.txt", "content": "alpha"}, {"name": "b.txt", "content": "beta"}])
    assert "补充背景知识" in out
    assert "alpha" in out and "beta" in out

    assert node._render_prompt("", "n1") == ""
    rendered = node._render_prompt("hello {{flow_id}}", "n1")
    assert rendered == "hello flow-1"

    with patch(
        "apps.opspilot.utils.chat_flow_utils.nodes.agent.agent.safe_render",
        side_effect=TemplateSecurityError("bad"),
    ):
        with pytest.raises(ValueError, match="模板包含不安全内容"):
            node._render_prompt("{{x}}", "n1")

    with patch(
        "apps.opspilot.utils.chat_flow_utils.nodes.agent.agent.safe_render",
        side_effect=RuntimeError("render-down"),
    ):
        assert node._render_prompt("keep-me", "n1") == "keep-me"


def test_truncate_memory_context_keeps_entries_until_limit():
    node = _node()
    assert node._truncate_memory_context("") == ""
    assert node._truncate_memory_context("short") == "short"

    long_plain = "x" * 50
    truncated = node._truncate_memory_context(long_plain, max_chars=20)
    assert truncated.startswith("x" * 20)
    assert truncated.endswith("...(记忆内容过长，已截断)")

    memories = "## first\n\n## second\n\n## third extra extra extra extra"
    kept = node._truncate_memory_context(memories, max_chars=20)
    assert kept.startswith("## first")
    assert "还有" in kept
    assert "third" not in kept


def test_build_final_message_injects_memory_files_and_list_payload():
    node = _node({"memory_context": "remember this"})
    combined = node._build_final_message("user-q", "prompt-{{flow_id}}", [{"name": "f.md", "content": "doc"}], "n1")
    assert "相关记忆" in combined
    assert "remember this" in combined
    assert "补充背景知识" in combined
    assert "user-q" in combined

    empty = _node()._build_final_message("plain", "", [], "n1")
    assert empty == "plain"

    payload = [{"type": "other"}, {"type": "message", "message": "hi"}]
    mutated = _node()._build_final_message(payload, "prefix", [], "n1")
    assert mutated[1]["message"].startswith("prefix")
    assert mutated[1]["message"].endswith("hi")


def test_resolve_trigger_type_and_attachment_tool_support():
    assert AgentNode._resolve_trigger_type({"entry_type": "celery"}) == "unattended"
    assert AgentNode._resolve_trigger_type({"entry_type": "test"}) == "unattended"
    assert AgentNode._resolve_trigger_type({"entry_type": "enterprise_wechat"}) == "third_party"
    assert AgentNode._resolve_trigger_type({"entry_type": "dingtalk"}) == "third_party"
    assert AgentNode._resolve_trigger_type({"entry_type": "wechat_official"}) == "third_party"
    assert AgentNode._resolve_trigger_type({"entry_type": "web_chat"}) == "interactive"
    assert AgentNode._skill_supports_attachment_generation(SimpleNamespace(tools=[])) is False
    assert AgentNode._skill_supports_attachment_generation(
        SimpleNamespace(tools=[{"name": BUILTIN_ATTACHMENT_FILE_TOOL_NAME}])
    ) is True


def test_set_llm_params_requires_skill_id_and_missing_skill():
    node = _node()
    with pytest.raises(ValueError, match="缺少 skill_id"):
        node.set_llm_params("n1", {}, {"last_message": "hi"})
    with pytest.raises(ValueError, match="技能 999999 不存在"):
        node.set_llm_params("n1", {"agent": 999999}, {"last_message": "hi"})


def test_execute_failed_and_success_with_attachment_and_browser_steps():
    node = _node()
    config = {"data": {"config": {"outputParams": "last_message"}}}
    failed = {"success": False, "error": "down", "error_type": "LLM", "message": "fail-text"}
    with patch.object(node, "set_llm_params", return_value=({"execution_id": "e1"}, "skill", False)):
        with patch.object(ChatService, "invoke_chat", return_value=(failed, None, None)):
            out = node.execute("n1", config, {})
    assert out == {"success": False, "error": "down", "error_type": "LLM", "last_message": "fail-text"}

    ok = {"success": True, "message": "done", "browser_steps": [{"step": 1}]}
    with patch.object(node, "set_llm_params", return_value=({"execution_id": "exec-attach"}, "skill", True)):
        with patch.object(ChatService, "invoke_chat", return_value=(ok, None, None)):
            with patch.object(
                node,
                "_sync_generated_attachment_link",
                return_value={"n1": "/url", "generated_attachment": {"attachment_id": "a1"}},
            ) as sync:
                out = node.execute("n1", config, {})
    assert out["last_message"] == "done"
    assert out["browser_steps"] == [{"step": 1}]
    assert out["n1"] == "/url"
    assert out["generated_attachment"]["attachment_id"] == "a1"
    sync.assert_called_once_with("n1", "exec-attach")


def test_sync_generated_attachment_link_sets_variable_and_skips_missing():
    node = _node()
    assert node._sync_generated_attachment_link("", "exec-x") == {}
    assert node._sync_generated_attachment_link("n1", "") == {}
    assert node._sync_generated_attachment_link("missing-node", "exec-x") == {}

    asset = create_workflow_attachment_asset(
        execution_id="exec-sync",
        attachment_id="att-sync",
        filename="report.md",
        content_bytes=b"# r",
        mime_type="text/markdown",
        source_node_id="agent-sync",
    )
    out = node._sync_generated_attachment_link("agent-sync", "exec-sync")
    assert out["agent-sync"].startswith("/api/proxy/opspilot/bot_mgmt/workflow_attachment/download/")
    assert out["generated_attachment"]["attachment_id"] == asset.attachment_id
    assert out["generated_attachment"]["filename"] == "report.md"
    assert node.variable_manager.get_variable("agent-sync") == out["agent-sync"]


def test_sse_execute_delegates_to_stream_generator():
    node = _node()
    with patch.object(node, "set_llm_params", return_value=({"llm_model": 1}, "skill-a", False)):
        with patch("apps.opspilot.utils.sse_chat.create_stream_generator", return_value="stream-gen") as gen:
            out = node.sse_execute(
                "n1",
                {"data": {"config": {"inputParams": "last_message", "agent": 1}}},
                {"last_message": "hi"},
            )
    assert out == "stream-gen"
    gen.assert_called_once()
    assert gen.call_args.args[0] == {"llm_model": 1}
    assert gen.call_args.args[1] == "skill-a"
    assert gen.call_args.args[4] == "hi"


@pytest.mark.asyncio
async def test_agui_execute_yields_chunks_then_error_event():
    node = _node()
    graph = MagicMock()

    async def _stream(_req):
        yield "data: chunk\n\n"
        raise RuntimeError("stream-down")

    graph.agui_stream = _stream
    with patch.object(
        node,
        "set_llm_params",
        return_value=({"llm_model": 7, "show_think": True, "skill_type": "basic", "group": 1}, "skill-a", False),
    ):
        with patch(
            "apps.opspilot.utils.chat_flow_utils.nodes.agent.agent.LLMModel.objects.get",
            return_value=SimpleNamespace(id=7),
        ):
            with patch(
                "apps.opspilot.utils.chat_flow_utils.nodes.agent.agent.chat_service.format_chat_server_kwargs",
                return_value=({"k": 1}, None, None),
            ):
                with patch(
                    "apps.opspilot.utils.chat_flow_utils.nodes.agent.agent.create_agent_instance",
                    return_value=(graph, object()),
                ):
                    lines = [line async for line in node.agui_execute("n1", {"data": {"config": {}}}, {})]
    assert lines[0] == "data: chunk\n\n"
    payload = json.loads(lines[1].removeprefix("data: ").strip())
    assert payload["type"] == "ERROR"
    assert payload["error"] == "节点执行错误: stream-down"
    assert AgentsNode is AgentNode
