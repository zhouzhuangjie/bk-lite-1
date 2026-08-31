"""MonitorInstance 视图鉴权辅助：current_team 校验、ID 去重、组织越权拒绝。"""
from types import SimpleNamespace

import pytest

from apps.core.exceptions.base_app_exception import BaseAppException, UnauthorizedException
from apps.monitor.views.monitor_instance import (
    _build_actor_context,
    _ensure_instance_scope,
    _ensure_target_organizations,
    _get_authorized_scope_groups,
    _normalize_id_list,
)

pytestmark = pytest.mark.django_db


def test_normalize_id_list_skips_empty_and_dedupes():
    assert _normalize_id_list([None, "", "a", "a", 1, "1"]) == ["a", "1"]


def test_build_actor_context_requires_integer_current_team():
    user = SimpleNamespace(username="u", domain="d", is_superuser=True, group_list=[{"id": 1}])
    with pytest.raises(BaseAppException, match="缺少 current_team"):
        _build_actor_context(SimpleNamespace(user=user, COOKIES={}))
    with pytest.raises(BaseAppException, match="非法"):
        _build_actor_context(SimpleNamespace(user=user, COOKIES={"current_team": "abc"}))
    ctx = _build_actor_context(SimpleNamespace(user=user, COOKIES={"current_team": "3", "include_children": "1"}))
    assert ctx["current_team"] == 3
    assert ctx["include_children"] is True
    assert ctx["username"] == "u"


def test_authorized_scope_groups_superuser_none_and_empty_raises(monkeypatch):
    super_ctx = {"is_superuser": True}
    assert _get_authorized_scope_groups(super_ctx) is None
    monkeypatch.setattr(
        "apps.monitor.views.monitor_instance.InstanceConfigService._get_actor_scope_groups",
        lambda ctx: [],
    )
    with pytest.raises(UnauthorizedException):
        _get_authorized_scope_groups({"is_superuser": False})


def test_ensure_target_organizations_rejects_unowned_and_bad_values(monkeypatch):
    _ensure_target_organizations([1], {"is_superuser": True})
    with pytest.raises(BaseAppException, match="组织参数非法"):
        _ensure_target_organizations(["x"], {"is_superuser": False})
    monkeypatch.setattr(
        "apps.monitor.views.monitor_instance._get_authorized_scope_groups",
        lambda ctx: {1},
    )
    with pytest.raises(UnauthorizedException):
        _ensure_target_organizations([1, 2], {"is_superuser": False})
    _ensure_target_organizations([1], {"is_superuser": False})


def test_ensure_instance_scope_rejects_cross_org(monkeypatch):
    from apps.monitor.models import MonitorInstance, MonitorInstanceOrganization, MonitorObject

    obj = MonitorObject.objects.create(name="ScopeObj881", level="base")
    inst = MonitorInstance.objects.create(id="scope-inst-881", name="i", monitor_object=obj)
    MonitorInstanceOrganization.objects.create(monitor_instance=inst, organization=9)
    monkeypatch.setattr(
        "apps.monitor.views.monitor_instance._get_authorized_scope_groups",
        lambda ctx: {1},
    )
    with pytest.raises(UnauthorizedException, match="跨组织"):
        _ensure_instance_scope(["scope-inst-881"], {"is_superuser": False})
    assert _ensure_instance_scope(["scope-inst-881"], {"is_superuser": True}) == ["scope-inst-881"]
