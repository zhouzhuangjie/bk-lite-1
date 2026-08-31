"""第三方渠道 ChatFlow 基类：Bot 校验、结果抽取与去重缓存。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.http import HttpResponse

from apps.opspilot.utils.base_chat_flow_utils import BaseChatFlowUtils

pytestmark = pytest.mark.unit


class _Flow(BaseChatFlowUtils):
    channel_name = "测试渠道"
    channel_code = "test"
    cache_key_prefix = "cf-test"

    def send_reply(self, reply_text, sender_id, config):
        self.sent = (reply_text, sender_id, config)


def test_validate_bot_and_workflow_missing_paths():
    utils = _Flow(bot_id=9)
    with patch("apps.opspilot.utils.base_chat_flow_utils.Bot") as bot_model:
        bot_model.objects.filter.return_value.first.return_value = None
        flow, err = utils.validate_bot_and_workflow()
    assert flow is None
    assert isinstance(err, HttpResponse)
    assert err.content == b"success"

    bot = SimpleNamespace(id=9)
    with (
        patch("apps.opspilot.utils.base_chat_flow_utils.Bot") as bot_model,
        patch("apps.opspilot.utils.base_chat_flow_utils.BotWorkFlow") as wf_model,
    ):
        bot_model.objects.filter.return_value.first.return_value = bot
        wf_model.objects.filter.return_value.first.return_value = None
        flow, err = utils.validate_bot_and_workflow()
    assert flow is None
    assert isinstance(err, HttpResponse)

    empty = SimpleNamespace(id=1, flow_json=None)
    with (
        patch("apps.opspilot.utils.base_chat_flow_utils.Bot") as bot_model,
        patch("apps.opspilot.utils.base_chat_flow_utils.BotWorkFlow") as wf_model,
    ):
        bot_model.objects.filter.return_value.first.return_value = bot
        wf_model.objects.filter.return_value.first.return_value = empty
        flow, err = utils.validate_bot_and_workflow()
    assert flow is None

    ready = SimpleNamespace(id=1, flow_json={"nodes": []})
    with (
        patch("apps.opspilot.utils.base_chat_flow_utils.Bot") as bot_model,
        patch("apps.opspilot.utils.base_chat_flow_utils.BotWorkFlow") as wf_model,
    ):
        bot_model.objects.filter.return_value.first.return_value = bot
        wf_model.objects.filter.return_value.first.return_value = ready
        flow, err = utils.validate_bot_and_workflow()
    assert flow is ready
    assert err is None


def test_execute_chatflow_result_shapes_and_dedup_cache():
    utils = _Flow(bot_id=3)
    flow = SimpleNamespace()
    engine = MagicMock()
    with patch("apps.opspilot.utils.base_chat_flow_utils.create_chat_flow_engine", return_value=engine):
        engine.execute.return_value = {"success": False, "error": "bad"}
        assert utils.execute_chatflow_with_message(flow, "n1", "hi", "u") == "bad"
        engine.execute.return_value = {"success": True, "content": "ok"}
        assert utils.execute_chatflow_with_message(flow, "n1", "hi", "u") == "ok"
        engine.execute.return_value = "plain"
        assert utils.execute_chatflow_with_message(flow, "n1", "hi", "u") == "plain"
        engine.execute.return_value = ""
        assert utils.execute_chatflow_with_message(flow, "n1", "hi", "u") == "处理完成"

    store = {}

    class _Cache:
        def get(self, key):
            return store.get(key)

        def add(self, key, value, timeout=None):
            if key in store:
                return False
            store[key] = value
            return True

        def set(self, key, value, timeout=None):
            store[key] = value

        def delete(self, key):
            store.pop(key, None)

    with patch("apps.opspilot.utils.base_chat_flow_utils.cache", _Cache()):
        assert utils.is_message_processed("m1") is False
        assert utils.is_message_processed("m1") is True
        utils.mark_message_completed("m1")
        assert utils.is_message_processed("m1") is True
        utils.mark_message_failed("m1")
        assert utils.is_message_processed("m1") is False
