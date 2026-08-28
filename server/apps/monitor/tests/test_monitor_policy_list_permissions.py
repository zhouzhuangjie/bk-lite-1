"""MonitorPolicyViewSet.list：权限字段回填与分页。"""
import json
from unittest.mock import patch

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.monitor.constants.permission import PermissionConstants
from apps.monitor.models.monitor_object import MonitorObject
from apps.monitor.models.monitor_policy import MonitorPolicy
from apps.monitor.views.monitor_policy import MonitorPolicyViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()


def test_monitor_policy_list_attaches_instance_and_default_permission():
    user = UserFactory(domain="domain.com", is_superuser=True)
    obj = MonitorObject.objects.create(name="PolicyListObj883", level="base")
    granted = MonitorPolicy.objects.create(
        monitor_object=obj,
        name="granted-policy",
        algorithm="avg",
        alert_name="a1",
        collect_type="host",
    )
    other = MonitorPolicy.objects.create(
        monitor_object=obj,
        name="other-policy",
        algorithm="avg",
        alert_name="a2",
        collect_type="host",
    )
    with (
        patch("apps.monitor.views.monitor_policy.get_current_team", return_value=1),
        patch(
            "apps.monitor.views.monitor_policy.get_permission_rules",
            return_value={"instance": [{"id": granted.id, "permission": ["View"]}]},
        ),
        patch(
            "apps.monitor.views.monitor_policy.permission_filter",
            return_value=MonitorPolicy.objects.filter(id__in=[granted.id, other.id]),
        ),
        patch("apps.monitor.views.monitor_policy.parse_page_params", return_value=(1, 10)),
    ):
        request = factory.get("/policy/?monitor_object_id=" + str(obj.id))
        force_authenticate(request, user=user)
        request.COOKIES["current_team"] = "1"
        resp = MonitorPolicyViewSet.as_view({"get": "list"})(request)
    body = json.loads(resp.content)
    assert body["result"] is True
    assert body["data"]["count"] == 2
    perms = {item["name"]: item["permission"] for item in body["data"]["items"]}
    assert perms["granted-policy"] == ["View"]
    assert perms["other-policy"] == PermissionConstants.DEFAULT_PERMISSION
