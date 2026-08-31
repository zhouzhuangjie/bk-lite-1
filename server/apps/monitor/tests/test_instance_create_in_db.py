"""InstanceConfigService：事务内创建/复用实例、重建组织、批量默认规则。"""
import uuid

import pytest

from apps.monitor.models import (
    Metric,
    MetricGroup,
    MonitorInstance,
    MonitorInstanceOrganization,
    MonitorObject,
    MonitorObjectOrganizationRule,
    MonitorPlugin,
)
from apps.monitor.services.node_mgmt import InstanceConfigService

pytestmark = pytest.mark.django_db


def _objects():
    parent = MonitorObject.objects.create(name=f"Host-{uuid.uuid4().hex[:8]}")
    child = MonitorObject.objects.create(name=f"Process-{uuid.uuid4().hex[:8]}", parent=parent)
    plugin = MonitorPlugin.objects.create(name=f"plug-{uuid.uuid4().hex[:8]}", collector="Telegraf", collect_type="host")
    group = MetricGroup.objects.create(monitor_object=child, monitor_plugin=plugin, name="g1")
    metric = Metric.objects.create(
        monitor_object=child,
        monitor_plugin=plugin,
        metric_group=group,
        name="cpu_usage",
    )
    return parent, child, metric


def test_create_instances_in_db_reuses_existing_and_creates_new():
    parent, child, metric = _objects()
    exist_id = f"exist-{uuid.uuid4().hex[:8]}"
    new_id = f"new-{uuid.uuid4().hex[:8]}"
    existing = MonitorInstance.objects.create(
        id=exist_id,
        name="old-name",
        monitor_object=parent,
        auto=True,
        is_deleted=True,
        is_active=False,
    )
    MonitorInstanceOrganization.objects.create(monitor_instance=existing, organization=1)
    new_instances = [{"instance_id": new_id, "instance_name": "n1", "group_ids": [9]}]
    existing_instances = [{"instance_id": exist_id, "instance_name": "revived", "group_ids": [8, 9]}]
    created_ids, _rule_ids = InstanceConfigService._create_instances_in_db(
        new_instances, existing_instances, [exist_id], parent.id
    )
    assert created_ids == [new_id]
    existing.refresh_from_db()
    assert existing.name == "revived"
    assert existing.auto is False
    assert existing.is_deleted is False
    assert existing.is_active is True
    orgs = set(
        MonitorInstanceOrganization.objects.filter(monitor_instance_id=exist_id).values_list("organization", flat=True)
    )
    assert orgs == {8, 9}
    created = MonitorInstance.objects.get(id=new_id)
    assert created.name == "n1"
    assert created.monitor_object_id == parent.id
    new_orgs = set(
        MonitorInstanceOrganization.objects.filter(monitor_instance_id=new_id).values_list("organization", flat=True)
    )
    assert new_orgs == {9}
    rules = list(
        MonitorObjectOrganizationRule.objects.filter(monitor_instance_id__in=[exist_id, new_id])
    )
    assert {r.monitor_instance_id for r in rules} == {exist_id, new_id}
    assert all(r.monitor_object_id == child.id for r in rules)
    assert all(r.rule["filter"][0]["name"] == "instance_id" for r in rules)


def test_build_instance_objects_and_empty_batch_rules():
    objs, assocs, ids = InstanceConfigService._build_instance_objects(
        [{"instance_id": "i1", "instance_name": "n", "group_ids": [1, 2]}],
        99,
    )
    assert ids == ["i1"]
    assert len(objs) == 1
    assert objs[0].id == "i1"
    assert objs[0].name == "n"
    assert objs[0].monitor_object_id == 99
    assert [a.organization for a in assocs] == [1, 2]
    assert InstanceConfigService._batch_create_default_rules([], 1) == []
    parent = MonitorObject.objects.create(name=f"Solo-{uuid.uuid4().hex[:8]}")
    assert InstanceConfigService._batch_create_default_rules(
        [{"instance_id": "x", "group_ids": [1]}], parent.id
    ) == []
    assert InstanceConfigService._sync_existing_instance_attrs([], []) == 0
