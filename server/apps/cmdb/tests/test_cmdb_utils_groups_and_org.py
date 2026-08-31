"""CMDB 组织工具：默认组、扁平子组与树形收集。"""
import pytest

from apps.cmdb.utils.base import get_default_group_id, get_organization_and_children_ids, get_user_groups_flat
from apps.system_mgmt.models.user import Group

pytestmark = pytest.mark.django_db


def test_get_default_group_id_returns_default_root():
    group, _ = Group.objects.get_or_create(name="Default", parent_id=0)
    Group.objects.get_or_create(name="Default", parent_id=group.id)
    assert get_default_group_id() == [group.id]


def test_get_user_groups_flat_superuser_and_excludes_guest_for_normal_user():
    root = Group.objects.create(name="Root", parent_id=0)
    child = Group.objects.create(name="Child", parent_id=root.id)
    guest = Group.objects.create(name="OpsPilotGuest", parent_id=0)
    other = Group.objects.create(name="Other", parent_id=0)

    super_ids = set(get_user_groups_flat([{"id": root.id}], is_superuser=True))
    assert {root.id, child.id, guest.id, other.id}.issubset(super_ids)

    normal_ids = set(get_user_groups_flat([{"id": root.id}], is_superuser=False))
    assert root.id in normal_ids
    assert child.id in normal_ids
    assert guest.id not in normal_ids
    assert other.id not in normal_ids


def test_get_organization_and_children_ids_walks_nested_tree():
    tree = [
        {
            "id": 1,
            "subGroups": [
                {"id": 2, "subGroups": [{"id": 4}]},
                {"id": 3},
            ],
        },
        {"id": 9, "subGroups": [{"id": 10}]},
    ]
    assert get_organization_and_children_ids(tree, 1) == [1, 2, 4, 3]
    assert get_organization_and_children_ids(tree, 9) == [9, 10]
    assert get_organization_and_children_ids(tree, 99) == []
    assert get_organization_and_children_ids(tree, 2) == [2, 4]
