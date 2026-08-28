"""system_mgmt.nats_api 剩余鉴权/通道/OTP/蓝鲸登录契约。"""
from unittest.mock import patch

import jwt
import pyotp
import pytest
from django.contrib.auth.hashers import make_password

from apps.system_mgmt import nats_api
from apps.system_mgmt.models import Channel, Group, LoginModule, Role, User
from apps.system_mgmt.models.channel import ChannelChoices

pytestmark = pytest.mark.django_db


def _user(**kwargs):
    defaults = dict(
        username="remain-user",
        display_name="剩余用户",
        email="remain@example.com",
        password=make_password("secret-pass"),
        domain="domain.com",
        group_list=[1],
        disabled=False,
        otp_secret="",
    )
    defaults.update(kwargs)
    return User.objects.create(**defaults)


def test_generate_qr_code_by_user_id_missing_and_success():
    assert nats_api.generate_qr_code_by_user_id(999999) == {"result": False, "message": "User not found"}
    user = _user(username="qr-user")
    out = nats_api.generate_qr_code_by_user_id(user.id)
    assert out["result"] is True
    assert out["data"]["qr_code"]
    user.refresh_from_db()
    assert user.otp_secret


def test_verify_otp_code_by_user_id_paths():
    assert nats_api.verify_otp_code_by_user_id(999999, "000000") == {"result": False, "message": "User not found"}
    user = _user(username="otp-uid", otp_secret="")
    assert nats_api.verify_otp_code_by_user_id(user.id, "000000")["message"] == "OTP not configured for this user"
    secret = pyotp.random_base32()
    user.otp_secret = secret
    user.save()
    code = pyotp.TOTP(secret).now()
    assert nats_api.verify_otp_code_by_user_id(user.id, code) == {"result": True, "message": "Verification successful"}
    assert nats_api.verify_otp_code_by_user_id(user.id, "000000")["message"] == "Invalid OTP code"


def test_verify_otp_code_missing_user_and_unconfigured():
    assert nats_api.verify_otp_code("ghost", "000000", "1.1.1.1")["message"] == "User not found"
    user = _user(username="otp-none", otp_secret="")
    assert nats_api.verify_otp_code(user.username, "000000", "1.1.1.1")["message"] == "OTP not configured for this user"


def test_get_namespace_by_domain_found_and_missing():
    assert nats_api.get_namespace_by_domain("no.such")["result"] is False
    LoginModule.objects.create(
        name="bk-lite-mod",
        source_type="bk_lite",
        other_config={"domain": "corp.example", "namespace": "ns-a"},
    )
    out = nats_api.get_namespace_by_domain("corp.example")
    assert out == {"result": True, "data": "ns-a"}


def test_bk_lite_user_login_unknown_and_disabled(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    assert nats_api.bk_lite_user_login("ghost", "domain.com")["result"] is False
    user = _user(username="bk-disabled", disabled=True)
    out = nats_api.bk_lite_user_login(user.username, user.domain)
    assert out == {"result": False, "message": "User is disabled"}
    enabled = _user(username="bk-ok")
    ok = nats_api.bk_lite_user_login(enabled.username, enabled.domain)
    assert ok["result"] is True
    assert ok["data"]["token"]


def test_verify_bk_token_closed_open_and_success(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    closed = nats_api.verify_bk_token("tok")
    assert closed["data"]["bk_login_open"] is False

    group = Group.objects.create(name="蓝鲸", parent_id=0)
    LoginModule.objects.create(
        name="bk-login",
        source_type="bk_login",
        enabled=True,
        other_config={"bk_url": "https://bk.example", "app_id": "a", "app_token": "t", "root_group": "蓝鲸", "default_roles": []},
    )
    empty = nats_api.verify_bk_token("")
    assert empty["data"]["bk_login_open"] is True
    assert empty["data"]["user"] == {}
    assert empty["data"]["url"] == "https://bk.example"

    with patch("apps.system_mgmt.nats_api.get_bk_user_info", return_value=(False, {})):
        failed = nats_api.verify_bk_token("bad")
    assert failed["data"]["user"] == {}

    bk_user = {"username": "bk-u1", "domain": "domain.com", "email": "u@bk", "language": "zh-Hans", "time_zone": "Asia/Shanghai"}
    with patch("apps.system_mgmt.nats_api.get_bk_user_info", return_value=(True, bk_user)):
        ok = nats_api.verify_bk_token("good")
    assert ok["data"]["user"]["username"] == "bk-u1"
    payload = jwt.decode(ok["data"]["user"]["token"], "test-secret", algorithms=["HS256"])
    assert payload["user_id"] == User.objects.get(username="bk-u1").id
    assert group.id in User.objects.get(username="bk-u1").group_list


def test_send_msg_feishu_dingtalk_webhook_and_display_fallback():
    user = _user(username="chan-u", display_name="小红")
    feishu = Channel.objects.create(name="fs", channel_type=ChannelChoices.FEISHU_BOT, config={}, description="", team=[1])
    dingtalk = Channel.objects.create(name="dt", channel_type=ChannelChoices.DINGTALK_BOT, config={}, description="", team=[1])
    hook = Channel.objects.create(name="wh", channel_type=ChannelChoices.CUSTOM_WEBHOOK, config={}, description="", team=[1])
    with patch("apps.system_mgmt.nats_api.send_by_feishu_bot", return_value={"result": True}) as fs:
        assert nats_api.send_msg_with_channel(feishu.id, "t", "c", [user.id]) == {"result": True}
        assert "小红" in fs.call_args.args[3]
    with patch("apps.system_mgmt.nats_api.send_by_dingtalk_bot", return_value={"result": True}) as dt:
        assert nats_api.send_msg_with_channel(dingtalk.id, "t", "c", []) == {"result": True}
        assert dt.call_args.args[3] == []
    with patch("apps.system_mgmt.nats_api.send_by_dingtalk_bot", return_value={"result": True}) as dt2:
        assert nats_api.send_msg_with_channel(dingtalk.id, "t", "c", [user.id, "raw-name"]) == {"result": True}
        assert dt2.call_args.args[3] == [user.id, "raw-name"]
    with patch("apps.system_mgmt.nats_api.send_by_custom_webhook", return_value={"result": True}) as wh:
        assert nats_api.send_msg_with_channel(hook.id, "", "body", [user.id]) == {"result": True}
        wh.assert_called_once()


def test_init_user_default_attributes_creates_group_and_rejects_duplicate():
    guest_roles = []
    for app in ["opspilot", "cmdb", "monitor", "alarm", "log", "node", "mlops", "job"]:
        role, _ = Role.objects.get_or_create(name="guest", app=app, defaults={"menu_list": []})
        guest_roles.append(role.id)
    normal, _ = Role.objects.get_or_create(name="normal", app="opspilot", defaults={"menu_list": []})
    default_group, _ = Group.objects.get_or_create(name="InitDefaultRoot", parent_id=0, defaults={"description": ""})
    Group.objects.get_or_create(name="OpsPilotGuest", parent_id=0)
    user = _user(username="init-attr", group_list=[default_group.id], role_list=[normal.id])
    org_name = f"我的组织-{user.id}"
    with patch("apps.system_mgmt.nats_api.set_opspilot_guest_group_default_rule"):
        first = nats_api.init_user_default_attributes(user.id, org_name, default_group.id)
    assert first["result"] is True
    user.refresh_from_db()
    assert default_group.id not in user.group_list
    assert first["data"]["group_id"] in user.group_list
    assert normal.id not in user.role_list
    with patch("apps.system_mgmt.nats_api.set_opspilot_guest_group_default_rule"):
        dup = nats_api.init_user_default_attributes(user.id, org_name, default_group.id)
    assert dup == {"result": False, "message": "Group already exists"}


def test_search_channel_list_scoped_requires_actor():
    Channel.objects.create(name="c1", channel_type=ChannelChoices.EMAIL, config={}, description="", team=[1])
    empty = nats_api.search_channel_list_scoped({}, channel_type="email")
    assert empty["result"] is True
    assert empty["data"] == []
    admin_role, _ = Role.objects.get_or_create(name="admin", app="")
    admin = _user(username="chan-admin", role_list=[admin_role.id], group_list=[1])
    scoped = nats_api.search_channel_list_scoped(
        {
            "username": admin.username,
            "domain": admin.domain,
            "is_superuser": True,
            "group_list": [1],
            "current_team": 1,
        },
        channel_type="email",
        teams=[1],
    )
    assert scoped["result"] is True
    assert any(item["name"] == "c1" for item in scoped["data"])
