"""ChannelViewSet 剩余：team 解析、对象权限、OpsPilot 只读、test_send 契约。"""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.system_mgmt.models import Channel, ChannelChoices
from apps.system_mgmt.viewset.channel_viewset import ChannelViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()


def _body(resp):
    payload = resp.content if hasattr(resp, "content") else resp.rendered_content
    if hasattr(resp, "data") and resp.data is not None and not isinstance(payload, (bytes, bytearray)):
        return resp.data
    try:
        return json.loads(resp.content)
    except Exception:
        return resp.data


def test_parse_team_and_user_group_ids():
    vs = ChannelViewSet()
    assert vs._parse_team_ids(None) == ([], False)
    assert vs._parse_team_ids("3") == ([3], False)
    assert vs._parse_team_ids(4) == ([4], False)
    assert vs._parse_team_ids({"a": 1}) == ([], True)
    assert vs._parse_team_ids(["1", "x"]) == ([], True)
    super_user = SimpleNamespace(is_superuser=True)
    assert vs._get_user_group_ids(super_user) is None
    user = SimpleNamespace(is_superuser=False, group_list=[{"id": "1"}, {"id": "bad"}, 2, None])
    assert vs._get_user_group_ids(user) == {1, 2}


def test_validate_channel_permission_and_opspilot_readonly():
    vs = ChannelViewSet()
    req = SimpleNamespace(user=SimpleNamespace(is_superuser=True, locale="zh-Hans"))
    channel = Channel(name="c", channel_type=ChannelChoices.EMAIL, config={}, team=[1], description="")
    assert vs._validate_channel_permission(req, channel) == (True, None)

    req.user.is_superuser = False
    req.user.group_list = [{"id": 1}]
    ok, err = vs._validate_channel_permission(req, Channel(name="c", channel_type=ChannelChoices.EMAIL, config={}, team=[9], description=""))
    assert ok is False
    assert err.status_code == 403
    assert json.loads(err.content)["message"] == "无权访问该渠道"

    nats = Channel(name="n", channel_type=ChannelChoices.NATS, config={"source": "opspilot"}, team=[1], description="")
    blocked = vs._reject_if_opspilot_managed(req, nats)
    assert blocked.status_code == 403
    assert "不可编辑或删除" in json.loads(blocked.content)["message"]
    assert vs._reject_if_opspilot_managed(req, channel) is None


def test_filter_by_accessible_teams_and_update_settings_nats():
    vs = ChannelViewSet()
    qs = Channel.objects.all()
    super_user = SimpleNamespace(is_superuser=True)
    assert vs._filter_by_accessible_teams(qs, super_user) is qs
    empty = SimpleNamespace(is_superuser=False, group_list=[])
    assert list(vs._filter_by_accessible_teams(qs, empty)) == []

    actor = UserFactory(domain="domain.com", is_superuser=True)
    channel = Channel.objects.create(
        name="nats-1",
        channel_type=ChannelChoices.NATS,
        config={"source": "manual"},
        description="",
        team=[1],
    )
    req = factory.post(f"/channel/{channel.id}/update_settings/", {"config": {"url": "nats://x"}}, format="json")
    force_authenticate(req, user=actor)
    with patch("apps.system_mgmt.viewset.channel_viewset.log_operation"):
        resp = ChannelViewSet.as_view({"post": "update_settings"})(req, pk=channel.id)
    assert json.loads(resp.content)["result"] is True
    channel.refresh_from_db()
    assert channel.config == {"url": "nats://x"}


def test_test_send_unsupported_missing_email_and_bot_error():
    actor = UserFactory(domain="domain.com", is_superuser=True)
    actor.email = ""
    actor.display_name = "Ada"
    req = factory.post("/channel/test_send/", {"channel_type": "custom_webhook", "config": {}}, format="json")
    force_authenticate(req, user=actor)
    resp = ChannelViewSet.as_view({"post": "test_send"})(req)
    assert resp.status_code == 400
    assert resp.data["message"] == "Unsupported channel type"

    req = factory.post("/channel/test_send/", {"channel_type": ChannelChoices.EMAIL, "config": {}, "name": "mail"}, format="json")
    force_authenticate(req, user=actor)
    resp = ChannelViewSet.as_view({"post": "test_send"})(req)
    assert resp.status_code == 400
    assert resp.data["message"] == "Current user email is empty"

    actor.email = "ada@example.com"
    with patch("apps.system_mgmt.viewset.channel_viewset.send_email", return_value={"result": True}):
        req = factory.post("/channel/test_send/", {"channel_type": ChannelChoices.EMAIL, "config": {}, "name": "mail"}, format="json")
        force_authenticate(req, user=actor)
        resp = ChannelViewSet.as_view({"post": "test_send"})(req)
    assert resp.data == {"result": True}

    with patch(
        "apps.system_mgmt.viewset.channel_viewset.send_by_wecom_bot",
        return_value={"errcode": 40013, "errmsg": "invalid corpid"},
    ):
        req = factory.post(
            "/channel/test_send/",
            {"channel_type": ChannelChoices.ENTERPRISE_WECHAT_BOT, "config": {}, "name": "bot"},
            format="json",
        )
        force_authenticate(req, user=actor)
        resp = ChannelViewSet.as_view({"post": "test_send"})(req)
    assert resp.status_code == 400
    assert resp.data["message"] == "invalid corpid"
