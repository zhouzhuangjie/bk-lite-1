"""NATS token 鉴权：Pilot 机器人授权、撤销与组织用户范围。"""
import time

import jwt
import pytest
from django.contrib.auth.hashers import make_password

from unittest.mock import patch

from apps.system_mgmt import nats_api
from apps.system_mgmt.models import Group, GroupDataRule, Role, User, UserRule

pytestmark = pytest.mark.django_db


def _user(**kwargs):
    defaults = dict(
        username="pilot-u",
        display_name="Pilot",
        email="pilot@example.com",
        password=make_password("secret-pass"),
        domain="domain.com",
        group_list=[1],
        disabled=False,
        otp_secret="",
    )
    defaults.update(kwargs)
    return User.objects.create(**defaults)


def _token(user_id, secret="test-secret", **extra):
    payload = nats_api._build_jwt_payload(user_id)
    payload.update(extra)
    return jwt.encode(payload, secret, algorithm="HS256")


def test_get_pilot_permission_no_group_overlap_and_rule_paths(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    group = Group.objects.create(name="pilot-g", parent_id=0)
    user = _user(username="pilot-normal", group_list=[group.id], role_list=[])
    token = _token(user.id)

    assert nats_api.get_pilot_permission_by_token(token, bot_id=9, group_list=[999]) == {"result": False}

    allowed = nats_api.get_pilot_permission_by_token(token, bot_id=9, group_list=[group.id])
    assert allowed == {"result": True, "data": {"username": "pilot-normal"}}

    gdr_empty = GroupDataRule.objects.create(
        name="pilot-empty",
        app="opspilot",
        group_id=group.id,
        group_name=group.name,
        rules={"skill": [{"id": 1}]},
    )
    UserRule.objects.create(username=user.username, domain=user.domain, group_rule=gdr_empty)
    no_bot_key = nats_api.get_pilot_permission_by_token(token, bot_id=9, group_list=[group.id])
    assert no_bot_key == {"result": True, "data": {"username": "pilot-normal"}}

    gdr_empty.rules = {"bot": [{"id": 3}]}
    gdr_empty.save(update_fields=["rules"])
    denied = nats_api.get_pilot_permission_by_token(token, bot_id=9, group_list=[group.id])
    assert denied == {"result": False}

    gdr_empty.rules = {"bot": [{"id": 0}]}
    gdr_empty.save(update_fields=["rules"])
    wildcard = nats_api.get_pilot_permission_by_token(token, bot_id=9, group_list=[group.id])
    assert wildcard == {"result": True, "data": {"username": "pilot-normal"}}

    gdr_empty.rules = {"bot": [{"id": 9}]}
    gdr_empty.save(update_fields=["rules"])
    matched = nats_api.get_pilot_permission_by_token(token, bot_id=9, group_list=[group.id])
    assert matched == {"result": True, "data": {"username": "pilot-normal"}}


def test_revoke_token_missing_legacy_and_success(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    assert nats_api.revoke_token("") == {"result": False, "message": "Token is missing"}

    user = _user(username="revoke-u")
    legacy = jwt.encode({"user_id": user.id, "login_time": int(time.time())}, "test-secret", algorithm="HS256")
    legacy_out = nats_api.revoke_token(legacy)
    assert legacy_out == {"result": False, "message": "Token does not support revocation (missing jti/exp)"}

    token = _token(user.id)
    payload = jwt.decode(token, "test-secret", algorithms=["HS256"], options={"verify_exp": False})
    with patch("apps.system_mgmt.nats_api.blacklist_token") as blacklist:
        ok = nats_api.revoke_token(f"Basic {token}")
    assert ok == {"result": True, "message": "Token revoked"}
    blacklist.assert_called_once_with(payload["jti"], payload["exp"])


def test_get_group_users_scoped_invalid_and_unauthorized_group():
    group = Group.objects.create(name="scope-g", parent_id=0)
    user = _user(username="scope-u", group_list=[group.id])
    ctx = {
        "username": user.username,
        "domain": user.domain,
        "current_team": group.id,
        "is_superuser": True,
    }
    assert nats_api.get_group_users_scoped(ctx, group="bad") == {"result": True, "data": []}
    assert nats_api.get_group_users_scoped(ctx, group=999) == {"result": True, "data": []}
    listed = nats_api.get_group_users_scoped(ctx, group=group.id)
    assert listed["result"] is True
    assert any(item["username"] == "scope-u" for item in listed["data"])


def test_get_client_filters_by_non_admin_roles():
    from apps.system_mgmt.models import App

    App.objects.get_or_create(name="opspilot", defaults={"display_name": "Ops", "url": "/", "description": ""})
    other = App.objects.create(name="cmdb-extra-client", display_name="CMDB Extra", url="/", description="")
    role, _ = Role.objects.get_or_create(name="viewer", app="opspilot", defaults={"menu_list": []})
    user = _user(username="client-u", role_list=[role.id])
    missing = nats_api.get_client(username="ghost")
    assert missing == {"result": False, "message": "User not found"}
    out = nats_api.get_client(username=user.username, domain=user.domain)
    assert out["result"] is True
    names = {item["name"] for item in out["data"]}
    assert "opspilot" in names
    assert other.name not in names


def test_send_msg_wecom_email_nats_and_unsupported(monkeypatch):
    from apps.system_mgmt.models import Channel
    from apps.system_mgmt.models.channel import ChannelChoices

    user = _user(username="msg-u")
    missing = nats_api.send_msg_with_channel(999999, "t", "c", [user.id])
    assert missing == {"result": False, "message": "Channel not found"}

    email = Channel.objects.create(name="email-miss", channel_type=ChannelChoices.EMAIL, config={}, description="", team=[1])
    no_rcpt = nats_api.send_msg_with_channel(email.id, "t", "c", [999999])
    assert no_rcpt == {"result": False, "message": "No valid recipients found"}

    wecom = Channel.objects.create(name="wecom", channel_type=ChannelChoices.ENTERPRISE_WECHAT_BOT, config={}, description="", team=[1])
    with patch("apps.system_mgmt.nats_api.send_by_wecom_bot", return_value={"result": True}) as send:
        assert nats_api.send_msg_with_channel(wecom.id, "t", "hi", [user.id]) == {"result": True}
        assert send.call_args.args[2] == [user.display_name]

    nats_ch = Channel.objects.create(
        name="nats-raw",
        channel_type=ChannelChoices.NATS,
        config={"method_name": "receive_alert_events"},
        description="",
        team=[1],
    )
    with patch("apps.system_mgmt.nats_api.send_nats_message", return_value={"result": True}) as nats_send:
        assert nats_api.send_msg_with_channel(nats_ch.id, "", {"k": 1}, []) == {"result": True}
        nats_send.assert_called_once()

    unknown = Channel.objects.create(name="unk", channel_type="unknown", config={}, description="", team=[1])
    assert nats_api.send_msg_with_channel(unknown.id, "t", "c", []) == {
        "result": False,
        "message": "Unsupported channel type",
    }


def test_sync_opspilot_nats_channels_invalid_and_create_update_delete():
    from apps.system_mgmt.models import Channel
    from apps.system_mgmt.models.channel import ChannelChoices

    assert nats_api.sync_opspilot_nats_channels("bad", "bot", [1], []) == {
        "result": False,
        "message": "bot_id must be an integer",
    }
    first = nats_api.sync_opspilot_nats_channels(7, "告警Bot", [1], [{"node_id": "n1", "name": "入口"}, {"node_id": ""}])
    assert first == {"result": True, "data": {"created": 1, "updated": 0, "deleted": 0}}
    channel = Channel.objects.get(channel_type=ChannelChoices.NATS, name="告警Bot - 入口")
    assert channel.config["bot_id"] == 7
    assert channel.config["node_id"] == "n1"
    assert channel.config["source"] == "opspilot"

    updated = nats_api.sync_opspilot_nats_channels(7, "告警Bot", [2], [{"node_id": "n1", "name": "入口改"}])
    assert updated["result"] is True
    channel.refresh_from_db()
    assert channel.name == "告警Bot - 入口改"
    assert channel.team == [2]

    cleared = nats_api.sync_opspilot_nats_channels(7, "告警Bot", [2], [])
    assert cleared["result"] is True
    assert not Channel.objects.filter(id=channel.id).exists()
