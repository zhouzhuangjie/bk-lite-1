"""node_mgmt 权限：节点鉴权、组织分配与请求用户解析。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.node_mgmt.constants.node import NodeConstants
from apps.node_mgmt.utils import permission as perm

pytestmark = pytest.mark.unit


def test_get_request_user_prefers_authenticated_then_force_auth():
    authed = SimpleNamespace(is_authenticated=True)
    assert perm.get_request_user(SimpleNamespace(user=authed)) is authed
    guest = SimpleNamespace(is_authenticated=False)
    forced = SimpleNamespace(username="bot")
    assert perm.get_request_user(SimpleNamespace(user=guest, _force_auth_user=forced)) is forced


def test_get_node_permission_returns_empty_without_team_or_invalid_team():
    req = SimpleNamespace(COOKIES={}, user=SimpleNamespace(username="u"))
    with patch("apps.node_mgmt.utils.permission.get_current_team", return_value=None):
        assert perm.get_node_permission(req) == {}
    req = SimpleNamespace(COOKIES={"include_children": "1"}, user=SimpleNamespace(username="u"))
    with patch("apps.node_mgmt.utils.permission.get_current_team", return_value="abc"):
        assert perm.get_node_permission(req) == {}


def test_get_node_permission_empty_when_no_authorized_groups():
    req = SimpleNamespace(
        COOKIES={"include_children": "0"},
        user=SimpleNamespace(username="alice", domain="domain.com", is_superuser=False),
    )
    scoped = MagicMock()
    scoped.get_authorized_groups_scoped.return_value = {"data": []}
    with (
        patch("apps.node_mgmt.utils.permission.get_current_team", return_value="3"),
        patch("apps.node_mgmt.utils.permission.SystemMgmt", return_value=scoped),
    ):
        assert perm.get_node_permission(req) == {}
    scoped.get_authorized_groups_scoped.assert_called_once()


def test_authorize_node_ids_validates_required_existence_and_operate():
    nodes, err = perm.authorize_node_ids(SimpleNamespace(), [])
    assert nodes is None
    assert err.status_code == 400
    assert err.content  # JsonResponse

    missing_node = SimpleNamespace(id="n1")
    with (
        patch.object(perm.Node.objects, "filter") as flt,
        patch.object(perm, "get_node_permission", return_value={"team": [1]}),
        patch.object(perm, "get_node_permissions", return_value=["View"]),
    ):
        qs = MagicMock()
        qs.prefetch_related.return_value.distinct.return_value = [missing_node]
        flt.return_value = qs
        nodes, err = perm.authorize_node_ids(SimpleNamespace(), ["n1", "n2"])
        assert nodes is None
        assert b"node does not exist" in err.content

        qs.prefetch_related.return_value.distinct.return_value = [SimpleNamespace(id="n1")]
        nodes, err = perm.authorize_node_ids(SimpleNamespace(), ["n1"])
        assert nodes is None
        assert err.status_code == 403

        with patch.object(perm, "get_node_permissions", return_value=["View", "Operate"]):
            nodes, err = perm.authorize_node_ids(SimpleNamespace(), ["n1"])
            assert err is None
            assert [n.id for n in nodes] == ["n1"]


def test_authorize_target_organizations_superuser_and_group_descendants():
    req = SimpleNamespace(user=None)
    with patch.object(perm, "get_request_user", return_value=None):
        err = perm.authorize_target_organizations(req, None, [1])
        assert err.status_code == 403

    superuser = SimpleNamespace(is_superuser=True, group_list=[1])
    with patch.object(perm, "get_request_user", return_value=superuser):
        assert perm.authorize_target_organizations(req, None, [9]) is None

    user = SimpleNamespace(is_superuser=False, group_list=[])
    with patch.object(perm, "get_request_user", return_value=user):
        err = perm.authorize_target_organizations(req, None, [1])
        assert err.status_code == 403

    user = SimpleNamespace(is_superuser=False, group_list=[1])
    with (
        patch.object(perm, "get_request_user", return_value=user),
        patch("apps.system_mgmt.utils.group_utils.GroupUtils.get_group_with_descendants", return_value=[1, 2]),
    ):
        assert perm.authorize_target_organizations(req, None, [2]) is None
        err = perm.authorize_target_organizations(req, None, [9])
        assert err.status_code == 403
    assert perm.authorize_target_organizations(req, None, []) is None


def test_get_node_permissions_uses_instance_map_then_team_default():
    node = SimpleNamespace(id="n1", nodeorganization_set=SimpleNamespace(all=lambda: [SimpleNamespace(organization=3)]))
    assert perm.get_node_permissions(node, {"instance": [{"id": "n1", "permission": ["View"]}]}) == ["View"]
    assert perm.get_node_permissions(node, {"team": [3]}) == NodeConstants.DEFAULT_PERMISSION
    assert perm.get_node_permissions(node, {"team": [9]}) == []
