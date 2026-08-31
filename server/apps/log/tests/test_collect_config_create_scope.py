"""CollectTypeViewSet：创建日志分组字段发现权限短路、展示分类枚举。"""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.log.constants.collect_type import DISPLAY_CATEGORY_ORDER
from apps.log.models import CollectInstance, CollectInstanceOrganization, CollectType
from apps.log.views.collect_config import CollectTypeViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()


def _payload(resp):
    return json.loads(resp.content.decode("utf-8"))


def _user():
    return UserFactory(username="log-collect-su", domain="domain.com", roles=[], is_superuser=True)


def test_display_category_enum_uses_language_loader():
    user = _user()
    user.locale = "zh-Hans"
    req = factory.get("/collect_types/display_category_enum/")
    force_authenticate(req, user=user)
    lan = SimpleNamespace(get=lambda key: "主机日志" if key.endswith(".name") else "")
    with patch("apps.log.views.collect_config.LanguageLoader", return_value=lan):
        resp = CollectTypeViewSet.as_view({"get": "display_category_enum"})(req)
    assert resp.status_code == 200
    data = _payload(resp)["data"]
    ids = [item["id"] for item in data]
    assert ids == list(DISPLAY_CATEGORY_ORDER)
    assert data[0]["name"] == "主机日志"


def test_get_log_group_create_attrs_value_error_and_empty_orgs():
    vs = CollectTypeViewSet()
    req = SimpleNamespace()
    with patch(
        "apps.log.views.collect_config.LogAccessScopeService.get_manageable_organization_ids",
        side_effect=ValueError("组织无效"),
    ):
        resp = vs._get_log_group_create_attrs(req, "q", 1, 2)
    assert resp.status_code == 403
    assert _payload(resp)["message"] == "组织无效"

    with patch(
        "apps.log.views.collect_config.LogAccessScopeService.get_manageable_organization_ids",
        return_value=[],
    ):
        resp = vs._get_log_group_create_attrs(req, "q", 1, 2)
    assert resp.status_code == 403
    assert _payload(resp)["message"] == "当前用户无权限创建日志分组"


def test_get_log_group_create_attrs_success_and_empty_query(monkeypatch):
    vs = CollectTypeViewSet()
    collect_type = CollectType.objects.create(name="logfile", collector="Filebeat", icon="i")
    inst = CollectInstance.objects.create(id="ci-create-scope-1", name="i1", collect_type=collect_type)
    CollectInstanceOrganization.objects.create(collect_instance=inst, organization=11)
    monkeypatch.setattr(
        "apps.log.views.collect_config.LogAccessScopeService.get_manageable_organization_ids",
        lambda request: {11},
    )
    monkeypatch.setattr(vs, "_append_creation_scope_filter", lambda query, instance_ids: "")
    resp = vs._get_log_group_create_attrs(object(), "base", 1, 2)
    assert resp.status_code == 200
    assert _payload(resp)["data"] == []

    monkeypatch.setattr(vs, "_append_creation_scope_filter", lambda query, instance_ids: f"{query} AND inst")
    monkeypatch.setattr(
        "apps.log.views.collect_config.SearchService.all_field_names",
        lambda query, start, end, fields, resolved_groups=None: ["message", "level"],
    )
    resp = vs._get_log_group_create_attrs(object(), "base", 1, 2)
    assert _payload(resp)["data"] == ["message", "level"]
