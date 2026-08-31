"""MonitorPolicyViewSet.create / update / partial_update / destroy：副作用与字段回填。"""
import json
import uuid
from unittest.mock import MagicMock

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.monitor.models import MonitorAlert, PolicyOrganization
from apps.monitor.models.monitor_object import MonitorObject
from apps.monitor.models.monitor_policy import MonitorPolicy
from apps.monitor.views.monitor_policy import MonitorPolicyViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()


class _BaselineClear:
    def __init__(self, clear):
        self.clear = clear


def _user():
    user = UserFactory(username=f"policy-crud-{uuid.uuid4().hex[:8]}", domain="domain.com", is_superuser=True)
    user.permission = {"monitor": set()}
    return user


def _payload(obj_id, **extra):
    data = {
        "monitor_object": obj_id,
        "name": "cpu-high",
        "algorithm": "avg_over_time",
        "alert_name": "cpu",
        "collect_type": "host",
        "schedule": {"type": "min", "value": 5},
        "organizations": [1, 2],
        "enable_alerts": ["threshold"],
        "enable": True,
    }
    data.update(extra)
    return data


def test_create_sets_created_by_and_registers_task_orgs(monkeypatch):
    user = _user()
    obj = MonitorObject.objects.create(name=f"PolicyCreate-{uuid.uuid4().hex[:6]}", level="base")
    task = MagicMock()
    orgs = MagicMock()
    baselines = MagicMock()
    monkeypatch.setattr(MonitorPolicyViewSet, "update_or_create_task", task)
    monkeypatch.setattr(MonitorPolicyViewSet, "update_policy_organizations", orgs)
    monkeypatch.setattr(MonitorPolicyViewSet, "update_policy_baselines", baselines)
    monkeypatch.setattr(MonitorPolicyViewSet, "is_no_data_alert_enabled", lambda self, p: True)

    request = factory.post("/policy/", _payload(obj.id), format="json")
    force_authenticate(request, user=user)
    resp = MonitorPolicyViewSet.as_view({"post": "create"})(request)
    resp.render()
    body = json.loads(resp.content)
    assert resp.status_code == 201
    policy = MonitorPolicy.objects.get(name="cpu-high", created_by=user.username, monitor_object_id=obj.id)
    assert body["result"] is True
    assert body["code"] == "20100"
    assert body["data"]["id"] == policy.id
    assert policy.created_by == user.username
    assert policy.name == "cpu-high"
    task.assert_called_once_with(policy.id, {"type": "min", "value": 5})
    orgs.assert_called_once_with(policy.id, [1, 2])
    baselines.assert_called_once_with(policy.id, policy.enable_alerts)


def test_update_and_partial_update_refresh_schedule_orgs_and_enable(monkeypatch):
    user = _user()
    obj = MonitorObject.objects.create(name=f"PolicyUpdate-{uuid.uuid4().hex[:6]}", level="base")
    policy = MonitorPolicy.objects.create(
        monitor_object=obj,
        name="old",
        algorithm="avg_over_time",
        alert_name="cpu",
        collect_type="host",
        enable=True,
        enable_alerts=["threshold"],
        schedule={"type": "min", "value": 5},
    )
    task = MagicMock()
    orgs = MagicMock()
    baselines = MagicMock()
    close_cfg = MagicMock()
    enable = MagicMock()
    monkeypatch.setattr(MonitorPolicyViewSet, "update_or_create_task", task)
    monkeypatch.setattr(MonitorPolicyViewSet, "update_policy_organizations", orgs)
    monkeypatch.setattr(MonitorPolicyViewSet, "update_policy_baselines", baselines)
    monkeypatch.setattr(MonitorPolicyViewSet, "should_update_policy_baselines", lambda *a, **k: True)
    monkeypatch.setattr(MonitorPolicyViewSet, "baseline_state_changed", lambda *a, **k: True)
    monkeypatch.setattr(MonitorPolicyViewSet, "close_active_threshold_alerts_for_policy_config_change", close_cfg)
    monkeypatch.setattr(MonitorPolicyViewSet, "handle_policy_enable_change", enable)

    request = factory.put(
        f"/policy/{policy.id}/",
        _payload(obj.id, name="new-name", enable=False, schedule={"type": "min", "value": 10}),
        format="json",
    )
    force_authenticate(request, user=user)
    resp = MonitorPolicyViewSet.as_view({"put": "update"})(request, pk=policy.id)
    resp.render()
    assert resp.status_code == 200
    policy.refresh_from_db()
    assert policy.updated_by == user.username
    assert policy.name == "new-name"
    task.assert_called_once_with(policy.id, {"type": "min", "value": 10})
    orgs.assert_called_once_with(policy.id, [1, 2])
    baselines.assert_called_once()
    close_cfg.assert_called_once()
    enable.assert_called_once_with(policy.id, True, False)

    task.reset_mock()
    orgs.reset_mock()
    request = factory.patch(
        f"/policy/{policy.id}/",
        {"name": "patched", "schedule": {"type": "min", "value": 15}, "organizations": [9]},
        format="json",
    )
    force_authenticate(request, user=user)
    resp = MonitorPolicyViewSet.as_view({"patch": "partial_update"})(request, pk=policy.id)
    resp.render()
    assert resp.status_code == 200
    policy.refresh_from_db()
    assert policy.name == "patched"
    assert policy.updated_by == user.username
    assert task.call_args.args == (policy.id, {"type": "min", "value": 15})
    assert orgs.call_args.args == (policy.id, [9])


def test_destroy_clears_baseline_closes_alerts_and_deletes_task_orgs(monkeypatch):
    user = _user()
    obj = MonitorObject.objects.create(name=f"PolicyDestroy-{uuid.uuid4().hex[:6]}", level="base")
    policy = MonitorPolicy.objects.create(
        monitor_object=obj,
        name="to-delete",
        algorithm="avg_over_time",
        alert_name="cpu",
        collect_type="host",
    )
    PolicyOrganization.objects.create(policy=policy, organization=3)
    alert = MonitorAlert.objects.create(policy_id=policy.id, monitor_instance_id="h1", status="new")
    clear = MagicMock()
    close = MagicMock()
    monkeypatch.setattr(
        "apps.monitor.views.monitor_policy.PolicyBaselineService",
        lambda policy: _BaselineClear(clear),
    )
    monkeypatch.setattr(MonitorPolicyViewSet, "close_alerts", close)
    periodic = MagicMock()
    monkeypatch.setattr("apps.monitor.views.monitor_policy.PeriodicTask.objects.filter", lambda **kwargs: periodic)

    request = factory.delete(f"/policy/{policy.id}/")
    force_authenticate(request, user=user)
    resp = MonitorPolicyViewSet.as_view({"delete": "destroy"})(request, pk=policy.id)
    assert resp.status_code == 204
    clear.assert_called_once()
    close.assert_called_once()
    closed_alerts = close.call_args.args[1]
    assert [item.id for item in closed_alerts] == [alert.id]
    assert close.call_args.args[2] == user.username
    assert close.call_args.args[3] == "policy_deleted"
    periodic.delete.assert_called_once()
    assert not MonitorPolicy.objects.filter(id=policy.id).exists()
    assert not PolicyOrganization.objects.filter(policy_id=policy.id).exists()
