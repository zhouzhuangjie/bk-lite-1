"""认证后端剩余：重复 token、权限填充异常、token 校验异常、用户写库冲突。"""
from django.core.exceptions import MultipleObjectsReturned
from django.db import IntegrityError

import pytest

from apps.base.models import User as BaseUser
from apps.base.models import UserAPISecret
from apps.core import backends as be
from apps.core.backends import APISecretAuthBackend, AuthBackend
from apps.core.tests.test_backends_service import _Req

pytestmark = pytest.mark.django_db


def test_api_token_duplicate_user_returns_none(mocker):
    UserAPISecret.objects.create(username="dup", domain="domain.com", api_secret="dupsec", team=1)
    mocker.patch.object(BaseUser._default_manager, "get", side_effect=MultipleObjectsReturned())
    assert APISecretAuthBackend().authenticate(api_token="dupsec") is None


def test_api_token_populate_exception_logs_secret_owner(mocker):
    BaseUser.objects.create(username="boom", domain="domain.com")
    UserAPISecret.objects.create(username="boom", domain="domain.com", api_secret="boomsec", team=1)
    mocker.patch.object(APISecretAuthBackend, "_populate_user_permissions", side_effect=RuntimeError("perm down"))
    assert APISecretAuthBackend().authenticate(api_token="boomsec") is None


def test_get_user_all_roles_swallows_system_user_lookup_error(mocker):
    user = BaseUser.objects.create(username="ruser", domain="domain.com", group_list=[])
    mocker.patch.object(be.SystemUser.objects, "filter", side_effect=RuntimeError("db"))
    roles = APISecretAuthBackend()._get_user_all_roles(user)
    assert roles == set()


def test_auth_backend_authenticate_swallows_unexpected_error(mocker):
    mocker.patch.object(AuthBackend, "_verify_token_with_system_mgmt", side_effect=RuntimeError("rpc"))
    assert AuthBackend().authenticate(request=_Req(), token="t") is None


def test_verify_token_generic_error_reraises(mocker):
    client = mocker.MagicMock()
    client.verify_token.side_effect = RuntimeError("down")
    mocker.patch.object(be, "SystemMgmt", return_value=client)
    with pytest.raises(RuntimeError, match="down"):
        AuthBackend()._verify_token_with_system_mgmt("t")


def test_set_user_info_duplicate_and_integrity(mocker):
    info = {"username": "xuser", "domain": "domain.com", "roles": [], "group_list": [], "locale": "en"}
    mocker.patch.object(BaseUser._default_manager, "get_or_create", side_effect=MultipleObjectsReturned())
    assert AuthBackend().set_user_info(_Req(), info, {}) is None
    mocker.patch.object(BaseUser._default_manager, "get_or_create", side_effect=IntegrityError("dup"))
    assert AuthBackend().set_user_info(_Req(), info, {}) is None
    mocker.patch.object(BaseUser._default_manager, "get_or_create", side_effect=RuntimeError("save"))
    assert AuthBackend().set_user_info(_Req(), info, {}) is None


def test_set_user_info_updates_changed_fields():
    user = BaseUser.objects.create(
        username="upd",
        domain="domain.com",
        email="old@x.com",
        is_superuser=False,
        is_staff=False,
        is_active=False,
        group_list=[],
        roles=[],
        locale="en",
    )
    info = {
        "username": "upd",
        "domain": "domain.com",
        "email": "new@x.com",
        "is_superuser": True,
        "roles": ["admin"],
        "group_list": [{"id": 2}],
        "locale": "zh-Hans",
        "permission": {"cmdb": ["view"]},
        "role_ids": [1],
        "display_name": "U",
        "timezone": "Asia/Shanghai",
        "group_tree": [],
    }
    out = AuthBackend().set_user_info(_Req(path="/health/"), info, {"k": 1})
    user.refresh_from_db()
    assert out.pk == user.pk
    assert user.email == "new@x.com"
    assert user.is_superuser is True
    assert user.is_staff is True
    assert user.is_active is True
    assert user.group_list == [{"id": 2}]
    assert user.roles == ["admin"]
    assert user.locale == "zh-Hans"
    assert out.permission == {"cmdb": {"view"}}
    assert out.rules == {"k": 1}
