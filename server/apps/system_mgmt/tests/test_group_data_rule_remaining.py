"""GroupDataRule 剩余：actor 上下文、未知 APP、mlops group_id、空组织列表。"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.system_mgmt.models import GroupDataRule
from apps.system_mgmt.viewset.group_data_rule_viewset import (
    GroupDataRuleViewSet,
    _build_actor_context,
)

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()


def _body(resp):
    return json.loads(resp.content)


def test_build_actor_context_requires_and_parses_current_team():
    request = SimpleNamespace(COOKIES={}, user=SimpleNamespace(username="u", domain="d", is_superuser=True, group_list=[]))
    ctx, err = _build_actor_context(request, loader=None)
    assert ctx is None
    assert err.status_code == 400
    assert _body(err) == {"result": False, "message": "缺少 current_team 参数"}

    request.COOKIES = {"current_team": "bad"}
    ctx, err = _build_actor_context(request, loader=None)
    assert ctx is None
    assert _body(err) == {"result": False, "message": "current_team 参数非法"}

    request.COOKIES = {"current_team": "7", "include_children": "1"}
    request.user.group_list = [{"id": 7}]
    ctx, err = _build_actor_context(request, loader=None)
    assert err is None
    assert ctx == {
        "username": "u",
        "domain": "d",
        "current_team": 7,
        "include_children": True,
        "is_superuser": True,
        "group_list": [7],
    }


def test_get_client_unknown_app_raises():
    with pytest.raises(Exception, match="APP not found"):
        GroupDataRuleViewSet.get_client({"app": "unknown"})


def test_retrieve_disabled_returns_405_when_loader_missing():
    vs = GroupDataRuleViewSet()
    vs.loader = None
    resp = vs.retrieve(SimpleNamespace())
    assert resp.status_code == 405
    assert _body(resp) == {"result": False, "message": "接口未启用"}


def test_get_app_data_mlops_rejects_invalid_group_id():
    actor = UserFactory(domain="domain.com", is_superuser=True)
    actor.locale = "zh-Hans"
    request = factory.get("/x/", {"app": "mlops", "group_id": "bad"})
    force_authenticate(request, user=actor)
    resp = GroupDataRuleViewSet.as_view({"get": "get_app_data"})(request)
    assert resp.status_code == 400
    assert _body(resp) == {"result": False, "message": "group_id 参数非法"}


def test_list_returns_empty_when_user_has_no_groups():
    GroupDataRule.objects.create(name="hidden", app="cmdb", group_id=99, group_name="g", rules={})
    actor = UserFactory(domain="domain.com", is_superuser=False)
    actor.locale = "zh-Hans"
    actor.group_list = []
    actor.permission = {"data_permission-View"}
    request = factory.get("/x/")
    force_authenticate(request, user=actor)
    vs = GroupDataRuleViewSet.as_view({"get": "list"})
    resp = vs(request)
    body = _body(resp)
    assert body["result"] is True
    assert body["data"] == []


def test_get_app_data_returns_400_when_module_reports_failure(monkeypatch):
    actor = UserFactory(domain="domain.com", is_superuser=True)
    actor.locale = "en"
    client = MagicMock()
    client.get_module_data.return_value = {"result": False, "message": "rpc down"}
    monkeypatch.setattr(GroupDataRuleViewSet, "get_client", staticmethod(lambda params: client))
    request = factory.get("/x/", {"app": "cmdb", "page": "1", "page_size": "10"})
    request.COOKIES["current_team"] = "1"
    force_authenticate(request, user=actor)
    resp = GroupDataRuleViewSet.as_view({"get": "get_app_data"})(request)
    assert resp.status_code == 400
    assert _body(resp) == {"result": False, "message": "rpc down"}
