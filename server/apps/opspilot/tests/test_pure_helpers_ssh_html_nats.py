"""纯函数：SSH URI、HTML 清理、NATS 节点提取、函数节点、LangChain reasoning patch。"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from apps.opspilot.metis.llm.chain import lc_patches
from apps.opspilot.metis.llm.tools.fetch.formatter import _simple_html_clean
from apps.opspilot.metis.llm.tools.fetch.utils import clean_html_tags
from apps.opspilot.metis.llm.tools.ssh.utils import parse_ssh_uri
from apps.opspilot.services.nats_channel_sync import extract_nats_nodes, sync_opspilot_nats_channels_for_bot
from apps.opspilot.utils.chat_flow_utils.nodes.function.function import FunctionNode

pytestmark = pytest.mark.unit


def test_parse_ssh_uri_full_and_invalid_port():
    parsed = parse_ssh_uri("ssh://alice@10.0.0.1:2222/var/log/app")
    assert parsed == {"host": "10.0.0.1", "username": "alice", "port": 2222, "path": "/var/log/app"}
    fallback = parse_ssh_uri("bob@example.com:notaport/tmp")
    assert fallback["username"] == "bob"
    assert fallback["host"] == "example.com:notaport"
    assert fallback["port"] == 22
    no_user = parse_ssh_uri("only-host")
    assert no_user["host"] == "only-host"
    assert no_user["username"] is None


def test_clean_html_tags_and_simple_fallback_strip_script_and_entities():
    raw = (
        "<html><script>alert(1)</script><style>p{}</style>"
        "<!--c--><p>A&nbsp;&lt;B&gt;&amp;&quot;&#39;</p></html>"
    )
    cleaned = clean_html_tags(raw)
    assert "alert" not in cleaned
    assert "script" not in cleaned.lower()
    assert cleaned == 'A <B>&"\''
    assert _simple_html_clean(raw) == cleaned


def test_extract_nats_nodes_skips_non_nats_and_missing_id():
    assert extract_nats_nodes("not-a-dict") == []
    flow = {
        "nodes": [
            {"id": "n1", "type": "nats", "data": {"label": "告警入口"}},
            {"id": "n2", "type": "llm"},
            {"type": "nats", "data": {"label": "无 id"}},
            "bad",
        ]
    }
    assert extract_nats_nodes(flow) == [{"node_id": "n1", "name": "告警入口"}]


def test_sync_opspilot_nats_channels_failure_does_not_raise(monkeypatch):
    monkeypatch.setattr(
        "apps.opspilot.services.nats_channel_sync.BotWorkFlow.objects.filter",
        lambda **k: SimpleNamespace(order_by=lambda *_: SimpleNamespace(first=lambda: None)),
    )

    class Boom:
        def sync_opspilot_nats_channels(self, **k):
            raise RuntimeError("rpc down")

    monkeypatch.setattr("apps.opspilot.services.nats_channel_sync.SystemMgmt", Boom)
    bot = SimpleNamespace(id=9, name="bot", team=[1])
    out = sync_opspilot_nats_channels_for_bot(bot)
    assert out["result"] is False
    assert out["message"] == "rpc down"


def test_function_node_builtin_and_passthrough():
    node = FunctionNode(MagicMock())
    cfg = {"data": {"config": {"params": {"function_name": "upper", "function_args": {"text": "ab"}}}}}
    assert node.execute("fn1", cfg, {"last_message": "xy"}) == {"last_message": "AB"}
    echo_cfg = {"data": {"config": {"params": {"function_name": "echo", "function_args": {"message": "hi"}}}}}
    assert node.execute("fn2", echo_cfg, {}) == {"last_message": "hi"}
    empty = {"data": {"config": {}}}
    assert node.execute("fn3", empty, {"last_message": "keep"}) == {"last_message": "keep"}
    with pytest.raises(ValueError, match="未知的函数"):
        node.execute("fn4", {"data": {"config": {"params": {"function_name": "nope"}}}}, {})


def test_patched_create_chat_result_injects_reasoning_content(monkeypatch):
    class ChoiceMsg:
        reasoning_content = "think-1"
        model_extra = {}

    class BM:
        pass

    class RawResp(BM):
        choices = [SimpleNamespace(message=ChoiceMsg())]

    gen_msg = AIMessage(content="ans")
    result = SimpleNamespace(generations=[SimpleNamespace(message=gen_msg)])
    monkeypatch.setattr(lc_patches.openai, "BaseModel", BM)
    monkeypatch.setattr(lc_patches, "_original_create_chat_result", lambda self, resp, info=None: result)
    out = lc_patches._patched_create_chat_result(object(), RawResp())
    assert out.generations[0].message.additional_kwargs["reasoning_content"] == "think-1"
