"""组织规则视图鉴权：范围为空、规则过滤、绑定校验与写操作。"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.core.exceptions.base_app_exception import BaseAppException, UnauthorizedException
from apps.monitor.models import MonitorInstance, MonitorObject, MonitorObjectOrganizationRule
from apps.monitor.views import organization_rule as org_view

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()


def _superuser():
    return UserFactory(domain="domain.com", is_superuser=True)


def test_get_authorized_scope_groups_empty_raises(monkeypatch):
    monkeypatch.setattr(
        org_view.InstanceConfigService,
        "_get_actor_scope_groups",
        staticmethod(lambda ctx: []),
    )
    with pytest.raises(UnauthorizedException, match="当前组织无可用权限范围"):
        org_view._get_authorized_scope_groups({"is_superuser": False})
    assert org_view._get_authorized_scope_groups({"is_superuser": True}) is None


def test_rule_is_authorized_rejects_empty_and_cross_org(monkeypatch):
    rule = SimpleNamespace(organizations=[], monitor_instance_id="", monitor_object_id=1)
    assert org_view._rule_is_authorized(rule, {"is_superuser": False}) is False

    monkeypatch.setattr(org_view, "_get_authorized_scope_groups", lambda ctx: {1})
    rule.organizations = [1, 2]
    assert org_view._rule_is_authorized(rule, {"is_superuser": False}) is False

    rule.organizations = [1]
    assert org_view._rule_is_authorized(rule, {"is_superuser": False}) is True


def test_rule_is_authorized_checks_instance_cache(monkeypatch):
    monkeypatch.setattr(org_view, "_get_authorized_scope_groups", lambda ctx: {1})

    class QS:
        def values_list(self, *a, **k):
            return ["inst-ok"]

    monkeypatch.setattr(
        org_view.InstanceConfigService,
        "_get_authorized_monitor_instances",
        staticmethod(lambda *a, **k: QS()),
    )
    rule = SimpleNamespace(organizations=[1], monitor_instance_id="inst-ok", monitor_object_id=9)
    cache = {}
    assert org_view._rule_is_authorized(rule, {"is_superuser": False}, authorized_instance_cache=cache) is True
    assert org_view._rule_is_authorized(
        SimpleNamespace(organizations=[1], monitor_instance_id="inst-no", monitor_object_id=9),
        {"is_superuser": False},
        authorized_instance_cache=cache,
    ) is False
    assert (str(9), False) in cache


def test_validate_rule_binding_missing_instance():
    obj = MonitorObject.objects.create(name="BindMissR13", level="base")
    with pytest.raises(BaseAppException, match="监控实例不存在"):
        org_view._validate_rule_binding(obj.id, "('no-such',)")
    assert org_view._validate_rule_binding(None, None) is None


def test_validate_rule_payload_checks_instance_when_present(monkeypatch):
    request = SimpleNamespace()
    actor = {"is_superuser": True}
    monkeypatch.setattr(org_view, "_ensure_target_organizations", lambda orgs, ctx: None)
    called = {}

    def ensure_ops(req, ids, ctx):
        called["ids"] = ids

    monkeypatch.setattr(org_view, "_ensure_operate_instances", ensure_ops)
    monkeypatch.setattr(org_view, "_validate_rule_binding", lambda *a: called.setdefault("bound", True))
    org_view._validate_rule_payload(request, actor, 1, "inst-1", [1])
    assert called["ids"] == ["inst-1"]
    assert called["bound"] is True
    org_view._validate_rule_payload(request, actor, 1, "", [1])


def test_get_queryset_filters_unauthorized_rules(monkeypatch):
    obj = MonitorObject.objects.create(name="QSObjR13", level="base")
    allowed = MonitorObjectOrganizationRule.objects.create(
        monitor_object=obj, name="ok", organizations=[1], rule={},
    )
    MonitorObjectOrganizationRule.objects.create(
        monitor_object=obj, name="no", organizations=[9], rule={},
    )
    vs = org_view.MonitorObjectOrganizationRuleViewSet()
    vs.request = SimpleNamespace()
    vs.action = "list"
    monkeypatch.setattr(
        org_view, "_build_actor_context",
        lambda req: {"is_superuser": False, "current_team": 1},
    )
    monkeypatch.setattr(
        org_view, "_rule_is_authorized",
        lambda rule, actor, require_operate=False, authorized_instance_cache=None: rule.id == allowed.id,
    )
    ids = set(vs.get_queryset().values_list("id", flat=True))
    assert ids == {allowed.id}

    monkeypatch.setattr(org_view, "_rule_is_authorized", lambda *a, **k: False)
    assert list(vs.get_queryset()) == []

    vs.request = None
    assert vs.get_queryset().count() == 2


def test_create_update_partial_update_validate_then_delegate(monkeypatch):
    user = _superuser()
    obj = MonitorObject.objects.create(name="CRUDObjR13", level="base")
    rule = MonitorObjectOrganizationRule.objects.create(
        monitor_object=obj, name="r", organizations=[1], rule={},
    )
    vs = org_view.MonitorObjectOrganizationRuleViewSet()
    validated = []

    monkeypatch.setattr(
        org_view, "_build_actor_context",
        lambda req: {"is_superuser": True, "current_team": 1},
    )
    monkeypatch.setattr(
        org_view, "_validate_rule_payload",
        lambda *a, **k: validated.append(a),
    )
    monkeypatch.setattr(
        org_view.viewsets.ModelViewSet, "create",
        lambda self, request, *a, **k: org_view.WebUtils.response_success({"created": True}),
    )
    monkeypatch.setattr(
        org_view.viewsets.ModelViewSet, "update",
        lambda self, request, *a, **k: org_view.WebUtils.response_success({"updated": True}),
    )
    monkeypatch.setattr(
        org_view.viewsets.ModelViewSet, "partial_update",
        lambda self, request, *a, **k: org_view.WebUtils.response_success({"patched": True}),
    )
    vs.get_object = lambda: rule

    request = factory.post("/organization_rule/", {"monitor_object": obj.id, "organizations": [1]}, format="json")
    force_authenticate(request, user=user)
    resp = vs.create(request)
    assert json.loads(resp.content)["data"] == {"created": True}

    request = factory.put(f"/organization_rule/{rule.id}/", {"name": "r2"}, format="json")
    force_authenticate(request, user=user)
    resp = vs.update(request)
    assert json.loads(resp.content)["data"] == {"updated": True}

    request = factory.patch(f"/organization_rule/{rule.id}/", {"name": "r3"}, format="json")
    force_authenticate(request, user=user)
    resp = vs.partial_update(request)
    assert json.loads(resp.content)["data"] == {"patched": True}
    assert len(validated) == 3
