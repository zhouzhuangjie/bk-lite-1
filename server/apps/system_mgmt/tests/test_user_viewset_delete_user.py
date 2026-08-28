"""UserViewSet.delete_user：无权限 403；有权限删用户与 UserRule。"""
from types import SimpleNamespace
import json
import uuid

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.system_mgmt.models import Group, GroupDataRule, User, UserRule
from apps.system_mgmt.viewset.user_viewset import UserViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()


def test_delete_user_forbids_when_no_org_overlap():
    target = User.objects.create(
        username=f"del-t-{uuid.uuid4().hex[:8]}",
        display_name="t",
        email="t@example.com",
        password="x",
        group_list=[999],
        domain="domain.com",
    )
    operator = SimpleNamespace(is_superuser=False, group_list=[{"id": 1}], locale="zh-Hans")
    view = UserViewSet()
    ok, error = view._validate_target_user_permission(SimpleNamespace(user=operator), target)
    assert ok is False
    assert error.status_code == 403
    assert User.objects.filter(id=target.id).exists()


def test_delete_user_removes_user_and_rules():
    group = Group.objects.create(name=f"del-g-{uuid.uuid4().hex[:6]}")
    actor = UserFactory(domain="domain.com", is_superuser=True)
    actor.group_list = [{"id": group.id}]
    target = User.objects.create(
        username=f"del-ok-{uuid.uuid4().hex[:8]}",
        display_name="ok",
        email="ok@example.com",
        password="x",
        group_list=[group.id],
        domain="domain.com",
    )
    rule = GroupDataRule.objects.create(
        name="del-rule", group_id=group.id, group_name=group.name, app="monitor", rules={}
    )
    UserRule.objects.create(username=target.username, domain=target.domain, group_rule=rule)
    request = factory.post("/x/delete_user/", {"user_ids": [target.id]}, format="json")
    force_authenticate(request, user=actor)
    view = UserViewSet.as_view({"post": "delete_user"})
    resp = view(request)
    body = json.loads(resp.content)
    assert body["result"] is True
    assert not User.objects.filter(id=target.id).exists()
    assert not UserRule.objects.filter(username=target.username, domain=target.domain).exists()
