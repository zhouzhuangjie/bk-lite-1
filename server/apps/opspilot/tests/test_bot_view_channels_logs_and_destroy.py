"""BotViewSet：retrieve 回填测试 execution_id、渠道读写、destroy 清理、日志守卫。"""
import json
import uuid
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.opspilot.enum import WorkFlowTaskStatus
from apps.opspilot.models import Bot, BotChannel, BotWorkFlow, WorkFlowConversationHistory, WorkFlowTaskResult
from apps.opspilot.viewsets.bot_view import BotViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()
MOD = "apps.opspilot.viewsets.bot_view"


def _su(name="bot-ch-admin"):
    return UserFactory(username=f"{name}-{uuid.uuid4().hex[:8]}", domain="domain.com", roles=[], is_superuser=True, group_list=[{"id": 1, "name": "T1"}])


def _body(resp):
    if hasattr(resp, "content"):
        try:
            return json.loads(resp.content.decode("utf-8"))
        except Exception:
            pass
    return getattr(resp, "data", None)


def test_retrieve_fills_running_test_execution_id_only():
    user = _su("bot-ret")
    bot = Bot.objects.create(name="ret-bot", team=[1])
    flow = BotWorkFlow.objects.create(bot=bot, flow_json={}, web_json={})
    WorkFlowTaskResult.objects.create(
        bot_work_flow=flow,
        execution_id="prod-run",
        status=WorkFlowTaskStatus.RUNNING,
        input_data="{}",
        is_test=False,
    )
    WorkFlowTaskResult.objects.create(
        bot_work_flow=flow,
        execution_id="test-run",
        status=WorkFlowTaskStatus.RUNNING,
        input_data="{}",
        is_test=True,
    )
    req = factory.get(f"/{bot.id}/")
    force_authenticate(req, user=user)
    req.COOKIES["current_team"] = "1"
    resp = BotViewSet.as_view({"get": "retrieve"})(req, pk=bot.id)
    assert resp.data["execution_id"] == "test-run"


def test_get_bot_channels_validates_bot_and_masks_secrets():
    user = _su("bot-ch")
    missing = BotViewSet.as_view({"get": "get_bot_channels"})(factory.get("/"))
    # unauthenticated would 403; authenticate
    req = factory.get("/")
    force_authenticate(req, user=user)
    req.COOKIES["current_team"] = "1"
    missing = BotViewSet.as_view({"get": "get_bot_channels"})(req)
    assert missing.status_code == 400

    req404 = factory.get("/?bot_id=999999")
    force_authenticate(req404, user=user)
    req404.COOKIES["current_team"] = "1"
    not_found = BotViewSet.as_view({"get": "get_bot_channels"})(req404)
    assert not_found.status_code == 404

    bot = Bot.objects.create(name="ch-bot", team=[1])
    BotChannel.objects.create(
        bot=bot,
        name="web",
        channel_type="web",
        channel_config={"channels.web": {"token": "secret", "url": "http://x"}},
        enabled=True,
    )
    req_ok = factory.get(f"/?bot_id={bot.id}")
    force_authenticate(req_ok, user=user)
    req_ok.COOKIES["current_team"] = "1"
    ok = BotViewSet.as_view({"get": "get_bot_channels"})(req_ok)
    body = _body(ok)
    assert body["result"] is True
    channel = body["data"][0]
    assert channel["enabled"] is True
    assert channel["channel_config"]["channels.web"]["token"] == "******"
    assert channel["channel_config"]["channels.web"]["url"] == "http://x"


def test_update_bot_channel_toggles_enabled_and_config():
    user = _su("bot-upd-ch")
    bot = Bot.objects.create(name="upd-ch", team=[1])
    ch = BotChannel.objects.create(bot=bot, name="web", channel_type="web", channel_config={}, enabled=False)
    req = factory.post("/", {"id": ch.id, "enabled": True, "channel_config": {"k": {"v": 1}}}, format="json")
    force_authenticate(req, user=user)
    req.COOKIES["current_team"] = "1"
    resp = BotViewSet.as_view({"post": "update_bot_channel"})(req)
    assert _body(resp)["result"] is True
    ch.refresh_from_db()
    assert ch.enabled is True
    assert ch.channel_config["k"]["v"] == 1


def test_destroy_deletes_celery_and_nats_channels():
    user = _su("bot-del")
    bot = Bot.objects.create(name="del-bot", team=[1])
    BotWorkFlow.objects.create(bot=bot, flow_json={}, web_json={})
    req = factory.delete(f"/{bot.id}/")
    force_authenticate(req, user=user)
    req.COOKIES["current_team"] = "1"
    with (
        patch(f"{MOD}.delete_celery_task") as del_task,
        patch(f"{MOD}.cleanup_opspilot_nats_channels_for_bot") as cleanup,
        patch(f"{MOD}.log_operation"),
    ):
        resp = BotViewSet.as_view({"delete": "destroy"})(req, pk=bot.id)
    assert resp.status_code == 204
    del_task.assert_called_once_with(bot.id)
    cleanup.assert_called_once_with(bot.id)
    assert not Bot.objects.filter(id=bot.id).exists()


def test_search_workflow_log_requires_bot_and_aggregates_rows():
    user = _su("bot-log")
    req = factory.get("/")
    force_authenticate(req, user=user)
    req.COOKIES["current_team"] = "1"
    missing = BotViewSet.as_view({"get": "search_workflow_log"})(req)
    assert missing.status_code == 400

    req404 = factory.get("/?bot_id=999999")
    force_authenticate(req404, user=user)
    req404.COOKIES["current_team"] = "1"
    assert BotViewSet.as_view({"get": "search_workflow_log"})(req404).status_code == 404

    bot = Bot.objects.create(name="log-bot", team=[1])
    now = timezone.now()
    WorkFlowConversationHistory.objects.create(
        bot_id=bot.id,
        node_id="n1",
        user_id="alice",
        conversation_role="user",
        conversation_content="hello title",
        conversation_time=now,
        entry_type="web_chat",
        session_id="s1",
    )
    req_ok = factory.get(f"/?bot_id={bot.id}")
    force_authenticate(req_ok, user=user)
    req_ok.COOKIES["current_team"] = "1"
    resp = BotViewSet.as_view({"get": "search_workflow_log"})(req_ok)
    body = _body(resp)
    assert body["result"] is True
    assert body["data"]["count"] >= 1
    item = body["data"]["items"][0]
    assert item["user_id"] == "alice"
    assert "hello title" in item["title"]
    assert item["count"] == 1


def test_get_workflow_log_detail_paginates_and_maps_entry_type():
    user = _su("bot-log-d")
    bot = Bot.objects.create(name="logd-bot", team=[1])
    now = timezone.now()
    h = WorkFlowConversationHistory.objects.create(
        bot_id=bot.id,
        node_id="n1",
        user_id="bob",
        conversation_role="user",
        conversation_content="detail",
        conversation_time=now,
        entry_type="web_chat",
        session_id="s1",
    )
    req = factory.post("/", {"ids": [h.id], "bot_id": bot.id, "page": 1, "page_size": 10}, format="json")
    force_authenticate(req, user=user)
    req.COOKIES["current_team"] = "1"
    resp = BotViewSet.as_view({"post": "get_workflow_log_detail"})(req)
    body = _body(resp)
    assert body["result"] is True
    assert body["data"][0]["content"] == "detail"
    assert body["data"][0]["role"] == "user"

    bad_page = factory.post("/", {"ids": [h.id], "bot_id": bot.id, "page": 99, "page_size": 10}, format="json")
    force_authenticate(bad_page, user=user)
    bad_page.COOKIES["current_team"] = "1"
    empty = BotViewSet.as_view({"post": "get_workflow_log_detail"})(bad_page)
    assert _body(empty)["data"] == []


def test_non_superuser_denied_for_channels_and_authorize():
    user = UserFactory(
        username=f"bot-guest-{uuid.uuid4().hex[:8]}",
        domain="domain.com",
        roles=[],
        is_superuser=False,
        group_list=[{"id": 1, "name": "T1"}],
    )
    user.permission = {"opspilot": {"bot_channel-View", "bot_settings-Edit"}}
    bot = Bot.objects.create(name="deny-bot", team=[1])
    req = factory.get(f"/?bot_id={bot.id}")
    force_authenticate(req, user=user)
    req.COOKIES["current_team"] = "1"
    with patch.object(BotViewSet, "get_has_permission", return_value=False):
        resp = BotViewSet.as_view({"get": "get_bot_channels"})(req)
    assert _body(resp)["result"] is False

    auth_req = factory.post(f"/{bot.id}/authorize_usage_team/", {"usage_team": [2]}, format="json")
    force_authenticate(auth_req, user=user)
    auth_req.COOKIES["current_team"] = "1"
    with patch.object(BotViewSet, "get_has_permission", return_value=False):
        denied = BotViewSet.as_view({"post": "authorize_usage_team"})(auth_req, pk=bot.id)
    assert _body(denied)["result"] is False


def test_bot_create_and_update_writes_audit_and_workflow(monkeypatch):
    logs = []
    monkeypatch.setattr(f"{MOD}.log_operation", lambda request, action, app, summary: logs.append((action, summary)))
    monkeypatch.setattr(f"{MOD}.create_celery_task", lambda *a, **k: None)
    monkeypatch.setattr(f"{MOD}.sync_opspilot_nats_channels_for_bot", lambda bot: None)
    monkeypatch.setattr(f"{MOD}._schedule_memory_write_cache_flush", lambda *a, **k: None)
    user = _su("bot-crud")
    create_req = factory.post("/", {"name": "新工作台", "introduction": "i"}, format="json")
    force_authenticate(create_req, user=user)
    create_req.COOKIES["current_team"] = "1"
    created = BotViewSet.as_view({"post": "create"})(create_req)
    assert _body(created)["result"] is True
    bot = Bot.objects.get(name="新工作台")
    assert bot.team == [1]
    assert BotWorkFlow.objects.filter(bot_id=bot.id).exists()
    assert ("create", "新增工作台: 新工作台") in logs

    update_req = factory.put(
        f"/{bot.id}/",
        {
            "name": "改名工作台",
            "introduction": "j",
            "workflow_data": {"nodes": [{"id": "n1"}], "edges": []},
            "is_publish": True,
        },
        format="json",
    )
    force_authenticate(update_req, user=user)
    update_req.COOKIES["current_team"] = "1"
    updated = BotViewSet.as_view({"put": "update"})(update_req, pk=bot.id)
    assert _body(updated)["result"] is True
    bot.refresh_from_db()
    assert bot.name == "改名工作台"
    assert bot.online is True
    flow = BotWorkFlow.objects.get(bot_id=bot.id)
    assert flow.flow_json["nodes"][0]["id"] == "n1"
    assert ("update", "编辑工作台: 改名工作台") in logs
