"""Bot/Channel 初始化与 LLM tracing PII 脱敏契约。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch

import pytest

from apps.opspilot.enum import ChannelChoices
from apps.opspilot.metis.llm.common.tracing import setup_llm_tracing
from apps.opspilot.models import Channel, RasaModel
from apps.opspilot.services.bot_init_service import BotInitService
from apps.opspilot.services.channel_init_service import ChannelInitService

pytestmark = pytest.mark.django_db


def test_bot_init_saves_core_model_file_when_created():
    model = MagicMock()
    with (
        patch.object(RasaModel.objects, "update_or_create", return_value=(model, True)),
        patch("apps.opspilot.services.bot_init_service.open", mock_open(read_data=b"gz"), create=True),
    ):
        BotInitService("admin").init()
    model.model_file.save.assert_called_once()
    assert model.model_file.save.call_args.args[0] == "core_model.tar.gz"
    model.save.assert_called_once()


def test_bot_init_skips_file_when_already_exists():
    model = MagicMock()
    with patch.object(RasaModel.objects, "update_or_create", return_value=(model, False)):
        BotInitService("admin").init()
    model.model_file.save.assert_not_called()


def test_bot_init_swallows_exception(mocker):
    logger = mocker.patch("apps.opspilot.services.bot_init_service.logger")
    with patch.object(RasaModel.objects, "update_or_create", side_effect=RuntimeError("minio down")):
        BotInitService("admin").init()
    logger.exception.assert_called_once()
    assert "Failed to initialize Rasa model: minio down" in logger.exception.call_args.args[0]


def test_channel_init_creates_four_builtin_channels():
    Channel.objects.all().delete()
    ChannelInitService("admin").init()
    types = set(Channel.objects.filter(created_by="admin").values_list("channel_type", flat=True))
    assert types == {
        ChannelChoices.ENTERPRISE_WECHAT,
        ChannelChoices.DING_TALK,
        ChannelChoices.WEB,
        ChannelChoices.WECHAT_OFFICIAL_ACCOUNT,
    }
    ding = Channel.objects.get(channel_type=ChannelChoices.DING_TALK, created_by="admin")
    assert ding.channel_config["channels.dingtalk_channel.DingTalkChannel"]["enable_eventbus"] is False
    web = Channel.objects.get(channel_type=ChannelChoices.WEB, created_by="admin")
    assert web.channel_config == {"rest": {}}
    ChannelInitService("admin").init()
    assert Channel.objects.filter(created_by="admin").count() == 4


def test_setup_llm_tracing_redacts_sensitive_keys(mocker):
    captured = {}

    def fake_configure(span_processors):
        captured["fn"] = span_processors[0]

    mlflow = mocker.patch("apps.opspilot.metis.llm.common.tracing.mlflow")
    mocker.patch("apps.opspilot.metis.llm.common.tracing.configure", fake_configure)
    setup_llm_tracing("http://mlflow.local", "ops")
    mlflow.set_tracking_uri.assert_called_once_with("http://mlflow.local")
    mlflow.set_experiment.assert_called_once_with("ops")
    mlflow.langchain.autolog.assert_called_once()

    span = SimpleNamespace(
        inputs={"openai_api_key": "k", "prompt": "hi"},
        attributes={"session_token": "t", "model": "m"},
        outputs={"password": "p", "text": "ok"},
    )
    span.set_inputs = lambda data: setattr(span, "inputs", data)
    span.set_outputs = lambda data: setattr(span, "outputs", data)
    span.set_attribute = lambda key, value: span.attributes.__setitem__(key, value)

    captured["fn"](span)
    assert span.inputs == {"openai_api_key": "[REDACTED]", "prompt": "hi"}
    assert span.attributes == {"session_token": "[REDACTED]", "model": "m"}
    assert span.outputs == {"password": "[REDACTED]", "text": "ok"}
