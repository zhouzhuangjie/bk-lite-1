"""MonitorPolicyViewSet.template / preview：委托服务并回传精确 payload。"""
import json
from unittest.mock import patch
from uuid import uuid4

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.monitor.views.monitor_policy import MonitorPolicyViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()


def _user():
    return UserFactory(username=f"policy-tpl-{uuid4().hex[:8]}", domain="domain.com", is_superuser=True)


def test_template_returns_policy_service_payload():
    user = _user()
    templates = [{"name": "cpu-high", "template_key": "1:0"}]
    with patch(
        "apps.monitor.views.monitor_policy.PolicyService.get_policy_templates",
        return_value=templates,
    ) as svc:
        request = factory.post("/policy/template/", {"monitor_object_name": "Host"}, format="json")
        force_authenticate(request, user=user)
        resp = MonitorPolicyViewSet.as_view({"post": "template"})(request)
    svc.assert_called_once_with("Host")
    body = json.loads(resp.content)
    assert resp.status_code == 200
    assert body["result"] is True
    assert body["data"] == templates


def test_template_monitor_object_returns_distinct_ids():
    user = _user()
    with patch(
        "apps.monitor.views.monitor_policy.PolicyService.get_policy_templates_monitor_object",
        return_value=[11, 22],
    ) as svc:
        request = factory.get("/policy/template/monitor_object/")
        force_authenticate(request, user=user)
        resp = MonitorPolicyViewSet.as_view({"get": "template_monitor_object"})(request)
    svc.assert_called_once_with()
    body = json.loads(resp.content)
    assert body["result"] is True
    assert body["data"] == [11, 22]


def test_preview_returns_service_series():
    user = _user()
    payload = {"query": "up", "range": "5m"}
    with patch("apps.monitor.views.monitor_policy.PolicyPreviewService") as Preview:
        Preview.return_value.preview.return_value = {"series": [{"metric": "up", "value": 1}]}
        request = factory.post("/policy/preview/", payload, format="json")
        force_authenticate(request, user=user)
        resp = MonitorPolicyViewSet.as_view({"post": "preview"})(request)
    Preview.assert_called_once()
    Preview.return_value.preview.assert_called_once_with()
    body = json.loads(resp.content)
    assert body["result"] is True
    assert body["data"]["series"] == [{"metric": "up", "value": 1}]
