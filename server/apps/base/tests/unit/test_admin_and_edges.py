"""base.admin 与 user_api_secret viewset/serializer 边界补缺。

- UserAPISecretAdmin.save_model：空 secret 时生成明文再哈希落库；已哈希值幂等保留；明文会被哈希
- UserAPISecretViewSet.get_queryset：未认证 / team cookie 非整数 -> 空 queryset
- UserAPISecretSerializer.get_api_secret_preview：委托模型，空 secret -> 空串，非空 -> 统一掩码
只 mock super().save_model（admin 父类落库边界）与 request。
"""
import pydantic.root_model  # noqa

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.admin.sites import AdminSite

from apps.base.admin import UserAPISecretAdmin
from apps.base.models import UserAPISecret
from apps.base.user_api_secret_mgmt.serializers import UserAPISecretSerializer
from apps.base.user_api_secret_mgmt.views import UserAPISecretViewSet

pytestmark = pytest.mark.unit


class TestUserAPISecretAdminSaveModel:
    def _admin(self):
        return UserAPISecretAdmin(UserAPISecret, AdminSite())

    def test_无secret时自动生成并哈希存储(self):
        admin = self._admin()
        obj = UserAPISecret(username="u", domain="domain.com", api_secret="", team=0)
        with patch("apps.base.admin.admin.ModelAdmin.save_model") as super_save:
            admin.save_model(MagicMock(), obj, MagicMock(), change=False)
            super_save.assert_called_once()
        assert UserAPISecret.is_hashed_api_secret(obj.api_secret)
        digest = obj.api_secret[len(UserAPISecret.HASH_PREFIX) :]
        assert len(digest) == 64
        int(digest, 16)

    def test_已哈希secret保存时保持不变(self):
        admin = self._admin()
        hashed = UserAPISecret.hash_api_secret("keep-me")
        obj = UserAPISecret(username="u", domain="domain.com", api_secret=hashed, team=0)
        with patch("apps.base.admin.admin.ModelAdmin.save_model") as super_save:
            admin.save_model(MagicMock(), obj, MagicMock(), change=True)
            super_save.assert_called_once()
        assert obj.api_secret == hashed

    def test_明文secret保存时被哈希(self):
        admin = self._admin()
        obj = UserAPISecret(username="u", domain="domain.com", api_secret="EXISTING", team=0)
        with patch("apps.base.admin.admin.ModelAdmin.save_model") as super_save:
            admin.save_model(MagicMock(), obj, MagicMock(), change=True)
            super_save.assert_called_once()
        assert obj.api_secret != "EXISTING"
        assert obj.api_secret == UserAPISecret.hash_api_secret("EXISTING")


class TestViewSetGetQueryset:
    def _vs(self, request):
        vs = UserAPISecretViewSet()
        vs.request = request
        return vs

    def test_无request返回空queryset(self):
        vs = UserAPISecretViewSet()
        assert list(vs.get_queryset()) == []

    def test_未认证用户返回空queryset(self):
        request = MagicMock()
        request.user.is_authenticated = False
        qs = self._vs(request).get_queryset()
        assert list(qs) == []

    def test_team_cookie非整数返回空queryset(self):
        request = MagicMock()
        request.user.is_authenticated = True
        request.user.username = "alice"
        request.user.domain = "domain.com"
        with patch("apps.base.user_api_secret_mgmt.views.get_current_team", return_value="not-int"):
            qs = self._vs(request).get_queryset()
        assert list(qs) == []


class TestApiSecretPreviewEmpty:
    def test_空secret预览为空串(self):
        instance = UserAPISecret(username="u", domain="domain.com", api_secret="", team=0)
        request = MagicMock()
        request.user.group_list = []
        ser = UserAPISecretSerializer(context={"request": request})
        assert ser.get_api_secret_preview(instance) == ""

    def test_有secret返回统一掩码不泄露明文(self):
        instance = UserAPISecret(username="u", domain="domain.com", api_secret="abcd1234ef", team=0)
        request = MagicMock()
        request.user.group_list = []
        ser = UserAPISecretSerializer(context={"request": request})
        assert ser.get_api_secret_preview(instance) == "********"
        assert "abcd" not in ser.get_api_secret_preview(instance)
