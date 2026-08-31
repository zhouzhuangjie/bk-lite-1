"""GroupViewSet 剩余守卫：禁用 CRUD 文案、组织权限、创建父组校验、组内有用户禁止删除。"""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.system_mgmt.models import Group, User
from apps.system_mgmt.viewset.group_viewset import GroupViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()
BASE = "/api/v1/system_mgmt/group"


def _body(resp):
    return json.loads(resp.content)


def test_disabled_crud_returns_chinese_not_enabled_when_loader_missing():
    vs = GroupViewSet()
    vs.loader = None
    req = factory.get(BASE + "/")
    mapping = {
        "retrieve": vs.retrieve,
        "create": vs.create,
        "update": vs.update,
        "partial_update": vs.partial_update,
        "destroy": vs.destroy,
    }
    for name, method in mapping.items():
        resp = method(req)
        assert resp.status_code == 405, name
        assert _body(resp) == {"result": False, "message": "接口未启用"}


def test_validate_group_permission_blocks_non_member_and_allows_superuser():
    vs = GroupViewSet()
    vs.loader = None
    super_req = SimpleNamespace(user=SimpleNamespace(is_superuser=True))
    assert vs._validate_group_permission(super_req, 99) == (True, None)

    req = SimpleNamespace(user=SimpleNamespace(is_superuser=False))
    with patch.object(vs, "_get_user_group_ids", return_value={1, 2}):
        ok, err = vs._validate_group_permission(req, 9)
    assert ok is False
    assert err.status_code == 403
    assert _body(err)["message"] == "无权访问该组织"
    with patch.object(vs, "_get_user_group_ids", return_value={9}):
        assert vs._validate_group_permission(req, 9) == (True, None)


def test_check_create_permission_parent_scope():
    user = SimpleNamespace(is_superuser=False, group_list=[{"id": 3}])
    assert GroupViewSet._check_create_permission(SimpleNamespace(is_superuser=True), 99) is True
    assert GroupViewSet._check_create_permission(user, 0) is True
    assert GroupViewSet._check_create_permission(user, 3) is True
    assert GroupViewSet._check_create_permission(user, 9) is False


def test_get_detail_and_create_group_reject_unauthorized_parent():
    actor = UserFactory(domain="domain.com", is_superuser=False)
    actor.group_list = [{"id": 1}]
    actor.locale = "zh-Hans"
    actor.permission = {"system-manager": {"user_group-View", "user_group-Add Group"}}
    actor.save()
    outsider = Group.objects.create(name="Outsider", parent_id=0)

    req = factory.get(f"{BASE}/get_detail/", {"group_id": outsider.id})
    force_authenticate(req, user=actor)
    resp = GroupViewSet.as_view({"get": "get_detail"})(req)
    assert resp.status_code == 403
    assert _body(resp)["result"] is False

    create_req = factory.post(
        f"{BASE}/create_group/",
        {"group_name": "steal", "parent_group_id": outsider.id},
        format="json",
    )
    force_authenticate(create_req, user=actor)
    with patch("apps.system_mgmt.viewset.group_viewset.log_operation"):
        resp = GroupViewSet.as_view({"post": "create_group"})(create_req)
    assert _body(resp)["result"] is False
    assert not Group.objects.filter(name="steal").exists()


def test_delete_groups_rejects_when_users_exist():
    actor = UserFactory(domain="domain.com", is_superuser=True)
    actor.locale = "zh-Hans"
    g = Group.objects.create(name="HasUsers", parent_id=0)
    User.objects.create(
        username="member",
        domain="domain.com",
        group_list=[g.id],
        email="member@example.com",
        display_name="member",
        password="x",
    )
    req = factory.post(f"{BASE}/delete_groups/", {"id": g.id}, format="json")
    force_authenticate(req, user=actor)
    with (
        patch("apps.system_mgmt.viewset.group_viewset.log_operation"),
        patch("apps.system_mgmt.viewset.group_viewset.User.objects") as users,
    ):
        users.filter.return_value.exists.return_value = True
        resp = GroupViewSet.as_view({"post": "delete_groups"})(req)
    assert _body(resp)["result"] is False
    assert Group.objects.filter(id=g.id).exists()


def test_update_group_swallows_cmdb_sync_error():
    actor = UserFactory(domain="domain.com", is_superuser=True)
    g = Group.objects.create(name="SyncG", parent_id=0)
    req = factory.post(
        f"{BASE}/update_group/",
        {"group_id": g.id, "group_name": "SyncG2", "is_virtual": True},
        format="json",
    )
    force_authenticate(req, user=actor)
    with (
        patch("apps.system_mgmt.viewset.group_viewset.log_operation"),
        patch("apps.system_mgmt.viewset.group_viewset.CMDB") as cmdb,
    ):
        cmdb.return_value.sync_display_fields.side_effect = RuntimeError("cmdb down")
        resp = GroupViewSet.as_view({"post": "update_group"})(req)
    assert _body(resp)["result"] is True
    g.refresh_from_db()
    assert g.name == "SyncG2"
    assert g.is_virtual is True
