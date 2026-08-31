"""CMDB 实例权限：组织条件与任务规则折叠。"""
import pytest

from apps.cmdb.constants.constants import ORGANIZATION
from apps.cmdb.permissions.instance_permission import InstancePermissionManage, PermissionManage

pytestmark = pytest.mark.unit


def test_permission_manage_group_params_empty_and_list_any():
    empty = PermissionManage()
    assert empty.roles == []
    assert empty.user_groups == []
    assert empty.get_group_params() == []
    assert empty.get_permission_params() == []

    mgr = PermissionManage(roles=["operator"], user_groups=[{"id": 3}, {"id": 8}])
    assert mgr.get_group_params() == [{"field": ORGANIZATION, "type": "list_any[]", "value": [3, 8]}]
    assert mgr.get_permission_params() == mgr.get_group_params()


def test_instance_permission_manage_skips_wildcard_and_maps_ids():
    assert InstancePermissionManage.get_task_permissions(None) == {}
    assert InstancePermissionManage.get_task_permissions({}) == {}
    rules = {
        "collect": [{"id": "0", "permission": ["View"]}, {"id": "t1", "permission": ["Operate"]}],
        "import": [{"id": "t2", "permission": ["View"]}],
    }
    assert InstancePermissionManage.get_task_permissions(rules) == {"import": {"t2": ["View"]}}
