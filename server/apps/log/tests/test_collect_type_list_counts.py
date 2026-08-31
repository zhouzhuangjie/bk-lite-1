"""CollectTypeViewSet.list：按权限回填 policy_count / instance_count。"""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.log.models import CollectInstance, CollectType, Policy, PolicyOrganization
from apps.log.models.instance import CollectInstanceOrganization
from apps.log.views.collect_config import CollectTypeViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()


def _body(resp):
    return json.loads(resp.content.decode("utf-8"))


def test_list_adds_policy_and_instance_counts_for_authorized_only():
    ct = CollectType.objects.create(name="logfile", collector="Filebeat", icon="i", description="d")
    other = CollectType.objects.create(name="other", collector="Filebeat", icon="i", description="d")
    policy = Policy.objects.create(
        name="p1", collect_type=ct, alert_type="keyword", alert_name="n1", alert_level="warning"
    )
    PolicyOrganization.objects.create(policy=policy, organization=1)
    Policy.objects.create(
        name="p-other", collect_type=other, alert_type="keyword", alert_name="n2", alert_level="warning"
    )

    inst = CollectInstance.objects.create(id="inst-1", name="i1", collect_type=ct)
    CollectInstanceOrganization.objects.create(collect_instance=inst, organization=1)
    CollectInstance.objects.create(id="inst-2", name="i-other", collect_type=other)

    user = UserFactory(is_superuser=True)
    req = factory.get("/?add_policy_count=true&add_instance_count=true")
    force_authenticate(req, user=user)
    req.COOKIES["current_team"] = "1"
    lan = SimpleNamespace(get=lambda key: "")

    def fake_check(collect_type_id, obj_id, teams, permissions, cur_team):
        return int(collect_type_id) == ct.id and 1 in teams

    with patch("apps.log.views.collect_config.LanguageLoader", return_value=lan), patch(
        "apps.log.views.collect_config.get_permissions_rules",
        return_value={"data": {}, "team": [1]},
    ), patch(
        "apps.log.views.collect_config.check_instance_permission",
        side_effect=fake_check,
    ):
        resp = CollectTypeViewSet.as_view({"get": "list"})(req)

    rows = {row["name"]: row for row in _body(resp)["data"]}
    assert rows["logfile"]["policy_count"] == 1
    assert rows["logfile"]["instance_count"] == 1
    assert rows["other"]["policy_count"] == 0
    assert rows["other"]["instance_count"] == 0
