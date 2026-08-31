"""MonitorObjectViewSet：parent 查询、实例/策略计数权限过滤。"""
import pytest

from apps.monitor.models.monitor_object import MonitorInstance, MonitorInstanceOrganization, MonitorObject
from apps.monitor.models.monitor_policy import MonitorPolicy, PolicyOrganization

pytestmark = pytest.mark.django_db
BASE = "/api/v1/monitor"


def test_parent_query_param_filters_children_of_parent(api_client):
    parent = MonitorObject.objects.create(name="PKeep", level="base")
    MonitorObject.objects.create(name="CKeep", level="derivative", parent=parent)
    MonitorObject.objects.create(name="OtherChild", level="derivative")
    resp = api_client.get(f"{BASE}/api/monitor_object/?parent={parent.id}")
    names = {r["name"] for r in resp.json()["data"]}
    assert "CKeep" in names
    assert "PKeep" not in names
    assert "OtherChild" not in names


def test_list_adds_instance_and_policy_counts(api_client, mocker, authenticated_user):
    authenticated_user.is_superuser = True
    authenticated_user.save(update_fields=["is_superuser"])
    obj = MonitorObject.objects.create(name="CntObj", level="base")
    inst = MonitorInstance.objects.create(id="inst-1", name="i1", monitor_object=obj)
    MonitorInstanceOrganization.objects.create(monitor_instance=inst, organization=1)
    deleted = MonitorInstance.objects.create(id="inst-del", name="gone", monitor_object=obj, is_deleted=True)
    MonitorInstanceOrganization.objects.create(monitor_instance=deleted, organization=1)
    policy = MonitorPolicy.objects.create(monitor_object=obj, name="p1", algorithm="avg")
    PolicyOrganization.objects.create(policy=policy, organization=1)

    mocker.patch("apps.monitor.views.monitor_object.get_current_team", return_value=1)
    mocker.patch(
        "apps.monitor.views.monitor_object.get_permissions_rules",
        return_value={"data": {"all": True}, "team": [1]},
    )
    mocker.patch("apps.monitor.views.monitor_object.check_instance_permission", side_effect=lambda *a, **k: a[1] != "inst-del")

    resp = api_client.get(f"{BASE}/api/monitor_object/?add_instance_count=true&add_policy_count=true")
    assert resp.status_code == 200
    row = next(r for r in resp.json()["data"] if r["name"] == "CntObj")
    assert row["instance_count"] == 1
    assert row["policy_count"] == 1
