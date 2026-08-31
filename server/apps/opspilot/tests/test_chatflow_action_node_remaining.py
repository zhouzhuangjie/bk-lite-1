"""ChatFlow HTTP/通知节点：空 URL、模板失败、不支持方法、通知缺参。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests

from apps.core.utils.safe_template import TemplateSecurityError
from apps.opspilot.utils.chat_flow_utils.nodes.action.action import HttpActionNode, NotifyNode

pytestmark = pytest.mark.unit


class _VM:
    def __init__(self, variables=None):
        self._vars = variables or {}

    def get_all_variables(self):
        return self._vars

    def get_variable(self, name, default=None):
        return self._vars.get(name, default)


def test_http_render_template_security_error_and_fallback():
    node = HttpActionNode(_VM({"name": "ops"}))
    with patch(
        "apps.opspilot.utils.chat_flow_utils.nodes.action.action.safe_render",
        side_effect=TemplateSecurityError("bad tag"),
    ):
        with pytest.raises(ValueError, match="模板包含不安全内容: bad tag"):
            node._render_template("{{ name }}", "n1", {"name": "ops"})
    with patch(
        "apps.opspilot.utils.chat_flow_utils.nodes.action.action.safe_render",
        side_effect=RuntimeError("boom"),
    ):
        assert node._render_template("keep", "n1", {}) == "keep"
    assert node._render_template("", "n1", {}) == ""


def test_http_execute_requires_url_and_maps_timeout():
    node = HttpActionNode(_VM())
    with pytest.raises(ValueError, match="HTTP节点 n1 请求URL为空"):
        node.execute("n1", {"data": {"config": {}}}, {})
    with patch.object(node, "_send_http_request", side_effect=requests.exceptions.Timeout()):
        with pytest.raises(ValueError, match="HTTP请求超时: https://example.com"):
            node.execute("n1", {"data": {"config": {"url": "https://example.com"}}}, {})
    with patch.object(node, "_send_http_request", side_effect=requests.exceptions.ConnectionError("down")):
        with pytest.raises(ValueError, match="HTTP请求失败: down"):
            node.execute("n1", {"data": {"config": {"url": "https://example.com"}}}, {})


def test_http_send_rejects_method_and_posts_json_or_text():
    node = HttpActionNode(_VM())
    kwargs = {"timeout": 5, "headers": {}, "params": None}
    with pytest.raises(ValueError, match="不支持的HTTP方法: TRACE"):
        node._send_http_request("TRACE", "https://example.com", kwargs, {}, "n1", {})
    resp = SimpleNamespace(status_code=200)
    with patch("apps.opspilot.utils.chat_flow_utils.nodes.action.action.safe_post", return_value=resp) as post:
        out = node._send_http_request(
            "POST",
            "https://example.com",
            dict(kwargs),
            {"requestBody": '{"a": 1}'},
            "n1",
            {},
        )
    assert out is resp
    post.assert_called_once()
    assert post.call_args.kwargs["json"] == {"a": 1}

    with patch("apps.opspilot.utils.chat_flow_utils.nodes.action.action.safe_post", return_value=resp) as post:
        node._send_http_request("POST", "https://example.com", dict(kwargs), {"requestBody": "plain"}, "n1", {})
    assert post.call_args.kwargs["data"] == "plain"


def test_http_process_response_json_or_text():
    node = HttpActionNode(_VM())
    json_resp = MagicMock()
    json_resp.json.return_value = {"ok": True}
    assert node._process_response(json_resp) == {"ok": True}
    text_resp = MagicMock()
    text_resp.json.side_effect = ValueError("not json")
    text_resp.text = "hello"
    assert node._process_response(text_resp) == "hello"


def test_notify_execute_requires_channel_and_content_and_swallows_send_error():
    node = NotifyNode(_VM({"flow_input": {"user_ids": ["u1"]}}))
    with pytest.raises(ValueError, match="缺少通知渠道ID"):
        node.execute("n1", {"data": {"config": {"notificationContent": "hi"}}}, {})
    with pytest.raises(ValueError, match="缺少通知内容"):
        node.execute("n1", {"data": {"config": {"notificationMethod": 3}}}, {})
    with patch.object(node, "_send_notification", side_effect=RuntimeError("smtp down")):
        out = node.execute(
            "n1",
            {
                "data": {
                    "config": {
                        "notificationMethod": 3,
                        "notificationContent": "hi",
                        "notificationTitle": "t",
                        "notificationType": "sms",
                    }
                }
            },
            {},
        )
    assert out == {"last_message": "通知发送失败: smtp down"}


def test_http_headers_dict_or_list_and_get_without_body():
    node = HttpActionNode(_VM({"x": "1"}))
    assert node._process_key_value_pairs({"A": "1"}, "header", "n1", {}) == {"A": "1"}
    rendered = node._process_key_value_pairs(
        [{"key": "X", "value": "{{ x }}"}, "skip"],
        "header",
        "n1",
        {"x": "1"},
    )
    assert rendered == {"X": "1"}

    resp = SimpleNamespace(status_code=200)
    kwargs = {"timeout": 5, "headers": {}, "params": None}
    with patch("apps.opspilot.utils.chat_flow_utils.nodes.action.action.safe_get", return_value=resp) as get:
        out = node._send_http_request("GET", "https://example.com", dict(kwargs), {}, "n1", {})
    assert out is resp
    get.assert_called_once()
    assert "json" not in get.call_args.kwargs
    assert "data" not in get.call_args.kwargs

    with patch("apps.opspilot.utils.chat_flow_utils.nodes.action.action.safe_put", return_value=resp) as put:
        node._send_http_request("PUT", "https://example.com", dict(kwargs), {}, "n1", {})
    put.assert_called_once()
    assert "json" not in put.call_args.kwargs


def test_notify_receivers_fallback_and_send_contract():
    empty = NotifyNode(None)
    assert empty._resolve_receivers({}) == []
    node = NotifyNode(_VM({"flow_input": "bad"}))
    assert node._resolve_receivers({}) == []
    node = NotifyNode(_VM({"flow_input": {"user_ids": [" a ", "", None]}}))
    assert node._resolve_receivers({}) == ["a", "None"]
    node = NotifyNode(_VM())
    assert node._resolve_receivers({"notificationRecipients": ["u1", "u2"]}) == ["u1", "u2"]

    with patch("apps.opspilot.utils.chat_flow_utils.nodes.action.action.SystemMgmt") as client_cls:
        client_cls.return_value.send_msg_with_channel.return_value = {"result": True}
        out = node._send_notification(3, "t", "c", ["u1"], "n1", [{"filename": "a.md"}])
    assert out == {"result": True}
    client_cls.return_value.send_msg_with_channel.assert_called_once_with(
        channel_id=3,
        title="t",
        content="c",
        receivers=["u1"],
        attachments=[{"filename": "a.md"}],
    )

    with patch("apps.opspilot.utils.chat_flow_utils.nodes.action.action.SystemMgmt", side_effect=RuntimeError("rpc down")):
        failed = node._send_notification(3, "t", "c", ["u1"], "n1")
    assert failed == {"result": False, "error": "rpc down"}


def test_notify_attachments_require_execution_id_and_supported_type():
    node = NotifyNode(_VM())
    with pytest.raises(ValueError, match="当前工作流缺少 execution_id，无法解析附件"):
        node._build_attachments()

    md_file = MagicMock()
    md_file.read.return_value = b"hello"
    asset = SimpleNamespace(filename="note.md", file_knowledge=SimpleNamespace(file=md_file), created_at=None, id=1)
    with patch(
        "apps.opspilot.utils.chat_flow_utils.nodes.action.action.WorkflowAttachmentAsset.objects.filter",
        return_value=SimpleNamespace(order_by=lambda *a: [asset]),
    ):
        node.variable_manager = _VM({"execution_id": "exec-1"})
        attachments = node._build_attachments()
    assert attachments[0]["content"] == "aGVsbG8="
    assert attachments[0]["filename"].endswith(".md")
    md_file.open.assert_called_once_with("rb")
    md_file.close.assert_called_once()

    bad = SimpleNamespace(filename="note.exe", file_knowledge=SimpleNamespace(file=MagicMock()), created_at=None, id=2)
    with patch(
        "apps.opspilot.utils.chat_flow_utils.nodes.action.action.WorkflowAttachmentAsset.objects.filter",
        return_value=SimpleNamespace(order_by=lambda *a: [bad]),
    ):
        with pytest.raises(ValueError, match="附件 note.exe 类型不支持发送"):
            node._build_attachments()

    assert NotifyNode._build_email_attachment_filename("a.md", 0).endswith(".md")
    assert NotifyNode._build_email_attachment_filename("a.md", 1).endswith("_2.md")
    nameless = NotifyNode._build_email_attachment_filename("noext", 0)
    assert "." not in nameless
