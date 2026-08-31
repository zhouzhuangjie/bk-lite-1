"""MonitorPolicyViewSet.bulk_create_from_templates：必填校验与批量创建。"""
import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.core.exceptions.base_app_exception import BaseAppException
from apps.monitor.views.monitor_policy import MonitorPolicyViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()


def _user():
    u = UserFactory(username=f"policy-bulk-{uuid.uuid4().hex[:8]}", domain="domain.com", is_superuser=True)
    u.permission = {"monitor": set()}
    return u


def _call(data, user=None):
    user = user or _user()
    request = factory.post("/x/bulk_create_from_templates/", data, format="json")
    force_authenticate(request, user=user)
    view = MonitorPolicyViewSet.as_view({"post": "bulk_create_from_templates"})
    return view(request)


def test_bulk_create_requires_object_templates_and_assets():
    with pytest.raises(BaseAppException, match="monitor_object"):
        _call({"templates": [{}], "asset_ids": ["a"]})
    with pytest.raises(BaseAppException, match="templates"):
        _call({"monitor_object": 1, "asset_ids": ["a"]})
    with pytest.raises(BaseAppException, match="asset_ids"):
        _call({"monitor_object": 1, "templates": [{"name": "t"}]})


def test_bulk_create_saves_policies_and_registers_tasks(monkeypatch):
    user = _user()
    payloads = [
        {
            "name": "p1",
            "schedule": {"type": "min", "value": 5},
            "organizations": [1],
            "enable_alerts": ["threshold"],
        }
    ]
    policy = SimpleNamespace(id=77, enable_alerts=["threshold"])
    serializer = MagicMock()
    serializer.save.return_value = policy
    serializer.is_valid.return_value = True
    task_mock = MagicMock()
    org_mock = MagicMock()
    baseline_mock = MagicMock()

    monkeypatch.setattr(
        MonitorPolicyViewSet,
        "get_bulk_policy_assets",
        lambda self, obj_id, ids: [{"instance_id": "h1", "organizations": [1]}],
    )
    monkeypatch.setattr(
        MonitorPolicyViewSet,
        "enrich_bulk_policy_templates",
        lambda self, obj_id, templates: templates,
    )
    monkeypatch.setattr(
        "apps.monitor.views.monitor_policy.build_bulk_policy_payloads",
        lambda **kwargs: payloads,
    )
    monkeypatch.setattr(MonitorPolicyViewSet, "get_serializer", lambda self, *a, **k: serializer)
    monkeypatch.setattr(MonitorPolicyViewSet, "update_or_create_task", task_mock)
    monkeypatch.setattr(MonitorPolicyViewSet, "update_policy_organizations", org_mock)
    monkeypatch.setattr(MonitorPolicyViewSet, "update_policy_baselines", baseline_mock)
    monkeypatch.setattr(MonitorPolicyViewSet, "is_no_data_alert_enabled", lambda self, p: True)

    resp = _call(
        {"monitor_object": 3, "templates": [{"name": "t"}], "asset_ids": ["h1"], "config": {}},
        user=user,
    )
    body = json.loads(resp.content)
    assert body["result"] is True
    assert body["data"]["created_count"] == 1
    assert body["data"]["policy_ids"] == [77]
    task_mock.assert_called_once_with(77, payloads[0]["schedule"])
    org_mock.assert_called_once_with(77, [1])
    baseline_mock.assert_called_once()
