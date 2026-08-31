"""GroupViewSet 批量角色详情：父组继承链与未授权组织跳过。"""
import json
from types import SimpleNamespace

import pytest

from apps.system_mgmt.models import Group, Role
from apps.system_mgmt.viewset.group_viewset import GroupViewSet

pytestmark = pytest.mark.django_db


def test_batch_get_group_detail_inherits_parent_roles_and_skips_unauthorized():
    parent_role = Role.objects.create(name="inherit-r", app="cmdb")
    own_role = Role.objects.create(name="own-r", app="cmdb")
    parent = Group.objects.create(name="P-inherit", parent_id=0, allow_inherit_roles=True)
    parent.roles.add(parent_role)
    child = Group.objects.create(name="C-inherit", parent_id=parent.id)
    child.roles.add(own_role)
    outsider = Group.objects.create(name="Out", parent_id=0)

    user = SimpleNamespace(
        is_superuser=False,
        permission={"system-manager": {"user_group-View"}},
        group_list=[{"id": child.id}, {"id": parent.id}],
        locale="zh-Hans",
    )
    request = SimpleNamespace(user=user, data={"group_ids": [child.id, outsider.id]})
    resp = GroupViewSet().batch_get_group_detail_with_roles(request)
    body = json.loads(resp.content)
    assert body["result"] is True
    assert [row["group_id"] for row in body["data"]] == [child.id]
    row = body["data"][0]
    assert row["own_role_ids"] == [own_role.id]
    assert row["inherited_role_ids"] == [parent_role.id]
    assert row["inherited_role_source_map"] == {str(parent_role.id): "P-inherit"}
    assert row["inherited_role_source"] == "P-inherit"
