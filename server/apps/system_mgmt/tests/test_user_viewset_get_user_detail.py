"""UserViewSet.get_user_detail：超管可看角色/组规则，无组织交集返回 403。"""
import json
from types import SimpleNamespace

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.system_mgmt.models import Group, GroupDataRule, Role, User, UserRule
from apps.system_mgmt.viewset.user_viewset import UserViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()


def _body(resp):
    return json.loads(resp.content)


def test_get_user_detail_returns_roles_groups_and_rules():
    group = Group.objects.create(name="detail-g")
    role = Role.objects.create(name="detail-role", app="")
    group.roles.add(role)
    target = User.objects.create(
        username="detail-target",
        display_name="目标用户",
        email="t@example.com",
        password="hashed",
        group_list=[group.id],
        role_list=[role.id],
        domain="domain.com",
    )
    rule = GroupDataRule.objects.create(
        name="rule-1",
        group_id=group.id,
        group_name=group.name,
        app="monitor",
        rules={},
    )
    UserRule.objects.create(username=target.username, domain=target.domain, group_rule=rule)

    operator = UserFactory(is_superuser=True)
    req = factory.post("/", {"user_id": target.id}, format="json")
    force_authenticate(req, user=operator)
    resp = UserViewSet.as_view({"post": "get_user_detail"})(req)
    assert resp.status_code == 200
    payload = _body(resp)
    assert payload["result"] is True
    data = payload["data"]
    assert data["username"] == "detail-target"
    assert data["roles"][0]["role_id"] == role.id
    assert data["groups"][0]["id"] == group.id
    assert data["groups"][0]["rules"]["monitor"] == [rule.id]
    assert role.id in data["group_role_ids"]


def test_get_user_detail_forbidden_without_group_overlap():
    target = User.objects.create(
        username="hidden-user",
        display_name="hidden",
        email="h@example.com",
        password="hashed",
        group_list=[999],
        domain="domain.com",
    )
    operator = SimpleNamespace(
        is_superuser=False,
        group_list=[{"id": 1}],
        locale="zh-Hans",
    )
    view = UserViewSet()
    req = SimpleNamespace(user=operator)
    ok, error = view._validate_target_user_permission(req, target)
    assert ok is False
    assert error.status_code == 403
    assert json.loads(error.content)["result"] is False
