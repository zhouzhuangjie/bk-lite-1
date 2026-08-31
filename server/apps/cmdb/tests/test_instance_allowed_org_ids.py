"""InstanceViewSet._get_allowed_org_ids / 读权限判定：超管级联、普通用户无组织、实例读权。"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.cmdb.views.instance import InstanceViewSet
from apps.core.exceptions.base_app_exception import BaseAppException

VIEWS = "apps.cmdb.views.instance"


def _request(*, is_superuser, current_team=1, include_children="0", group_list=None):
    user = SimpleNamespace(is_superuser=is_superuser, group_list=group_list or [{"id": 1}])
    req = SimpleNamespace(user=user, COOKIES={"include_children": include_children})
    return req, current_team


def test_superuser_without_children_returns_current_team(monkeypatch):
    monkeypatch.setattr(f"{VIEWS}.get_current_team_from_request", lambda request: 7)
    req, _ = _request(is_superuser=True, include_children="0")
    assert InstanceViewSet._get_allowed_org_ids(req) == [7]


def test_superuser_include_children_uses_all_child_groups(monkeypatch):
    monkeypatch.setattr(f"{VIEWS}.get_current_team_from_request", lambda request: 3)
    monkeypatch.setattr(
        f"{VIEWS}.GroupUtils.get_all_child_groups",
        staticmethod(lambda group_id, include_self=True, group_list=None: [3, 31, 32]),
    )
    req, _ = _request(is_superuser=True, include_children="1")
    assert InstanceViewSet._get_allowed_org_ids(req) == [3, 31, 32]


def test_normal_user_empty_orgs_raises(monkeypatch):
    monkeypatch.setattr(f"{VIEWS}.get_current_team_from_request", lambda request: 9)
    monkeypatch.setattr(
        f"{VIEWS}.GroupUtils.get_user_authorized_child_groups",
        staticmethod(lambda **kwargs: []),
    )
    req, _ = _request(is_superuser=False, group_list=[{"id": 2}])
    with pytest.raises(BaseAppException, match="没有该组织的权限或组织选择无效"):
        InstanceViewSet._get_allowed_org_ids(req)


def test_normal_user_returns_authorized_orgs(monkeypatch):
    monkeypatch.setattr(f"{VIEWS}.get_current_team_from_request", lambda request: 4)
    captured = {}

    def _auth(*, user_group_list, target_group_id, include_children):
        captured["user_group_list"] = user_group_list
        captured["target_group_id"] = target_group_id
        captured["include_children"] = include_children
        return [4, 41]

    monkeypatch.setattr(
        f"{VIEWS}.GroupUtils.get_user_authorized_child_groups",
        staticmethod(_auth),
    )
    req, _ = _request(is_superuser=False, include_children="1", group_list=[{"id": 4}, {"id": 99}])
    assert InstanceViewSet._get_allowed_org_ids(req) == [4, 41]
    assert captured == {"user_group_list": [4, 99], "target_group_id": 4, "include_children": True}


def test_check_instance_read_permission_creator_org_and_rule(monkeypatch):
    vs = InstanceViewSet()
    vs.check_creator_and_organizations = MagicMock(return_value=True)
    assert vs._check_instance_read_permission(object(), {"id": "i1"}) is True

    vs.check_creator_and_organizations.return_value = False
    vs.organizations = MagicMock(return_value=[])
    assert vs._check_instance_read_permission(object(), {"id": "i1"}) is False

    vs.organizations.return_value = [1]
    monkeypatch.setattr(
        f"{VIEWS}.CmdbRulesFormatUtil.format_user_groups_permissions",
        lambda request, model_id="": {"map": 1},
    )
    monkeypatch.setattr(
        f"{VIEWS}.CmdbRulesFormatUtil.has_object_permission",
        lambda **kwargs: kwargs["instance"]["id"] == "ok",
    )
    assert vs._check_instance_read_permission(object(), {"id": "ok", "model_id": "host"}) is True
    assert vs._check_instance_read_permission(object(), {"id": "deny", "model_id": "host"}) is False
