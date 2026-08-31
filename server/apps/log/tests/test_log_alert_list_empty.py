"""日志 AlertViewSet.list：无权限策略时返回空 count/items。"""
import json

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.log.views.policy import AlertViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()


def test_log_alert_list_empty_when_no_policies(monkeypatch):
    user = UserFactory(domain="domain.com", is_superuser=True)
    monkeypatch.setattr(AlertViewSet, "_get_all_accessible_policy_ids", lambda self, request: [])
    request = factory.get("/api/v1/log/api/alert/")
    force_authenticate(request, user=user)
    request.COOKIES["current_team"] = "1"
    resp = AlertViewSet.as_view({"get": "list"})(request)
    body = json.loads(resp.content)
    assert body["data"]["count"] == 0
    assert body["data"]["items"] == []
