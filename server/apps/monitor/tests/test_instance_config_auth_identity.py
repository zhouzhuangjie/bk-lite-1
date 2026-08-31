"""InstanceConfigService：授权范围、接入清洗、Host/网络设备 identity。

对照权限契约：超管不过滤实例；无权限返回空集；无 node_ids 拒绝接入；
网络设备必须能解析 cloud_region + ip。
"""
from unittest.mock import patch

import pytest

from apps.core.exceptions.base_app_exception import BaseAppException, UnauthorizedException
from apps.monitor.models import CollectConfig, MonitorInstance, MonitorObject
from apps.monitor.models.plugin import MonitorPlugin
from apps.monitor.services.node_mgmt import InstanceConfigService as SVC

pytestmark = pytest.mark.django_db


def _ctx(**kwargs):
    data = {
        "username": "alice",
        "domain": "domain.com",
        "current_team": 1,
        "group_list": [1],
        "include_children": False,
        "is_superuser": False,
    }
    data.update(kwargs)
    return data


def test_actor_scope_groups_superuser_is_unrestricted():
    assert SVC._get_actor_scope_groups(_ctx(is_superuser=True)) is None
    with patch(
        "apps.monitor.services.node_mgmt.GroupUtils.get_user_authorized_child_groups",
        return_value=[1, 2],
    ):
        assert SVC._get_actor_scope_groups(_ctx()) == [1, 2]


def test_authorized_monitor_instances_superuser_and_empty_permission():
    obj = MonitorObject.objects.create(name="HostAuth-scope", level="base")
    MonitorInstance.objects.create(id="('h-auth',)", name="h", monitor_object=obj)
    qs = SVC._get_authorized_monitor_instances(_ctx(is_superuser=True), obj.id)
    assert qs.filter(id="('h-auth',)").exists()

    with patch("apps.monitor.services.node_mgmt.get_permission_rules", return_value={"team": [], "instance": []}):
        empty = SVC._get_authorized_monitor_instances(_ctx(), obj.id)
    assert list(empty) == []


def test_authorized_monitor_instances_team_or_instance_ids():
    obj = MonitorObject.objects.create(name="HostAuth2-scope", level="base")
    allowed = MonitorInstance.objects.create(id="('allow',)", name="a", monitor_object=obj)
    MonitorInstance.objects.create(id="('deny',)", name="d", monitor_object=obj)
    with patch(
        "apps.monitor.services.node_mgmt.get_permission_rules",
        return_value={"team": [], "instance": [{"id": allowed.id, "permission": ["View", "Operate"]}]},
    ):
        qs = SVC._get_authorized_monitor_instances(_ctx(), obj.id, require_operate=True)
    assert list(qs.values_list("id", flat=True)) == [allowed.id]


def test_authorized_collect_configs_superuser_and_unauthorized():
    obj = MonitorObject.objects.create(name="CfgObj-auth", level="base")
    plugin = MonitorPlugin.objects.create(name="CfgPlugin-auth")
    inst = MonitorInstance.objects.create(id="('cfg-i',)", name="i", monitor_object=obj)
    cfg = CollectConfig.objects.create(
        id="cfg-1",
        monitor_instance=inst,
        monitor_plugin=plugin,
        collector="Telegraf",
        collect_type="host",
        config_type="base",
        file_type="yaml",
        is_child=False,
    )
    assert SVC._get_authorized_collect_configs([]) == []
    assert [c.id for c in SVC._get_authorized_collect_configs([cfg.id])] == [cfg.id]
    assert [c.id for c in SVC._get_authorized_collect_configs([cfg.id], _ctx(is_superuser=True))] == [cfg.id]

    with patch.object(SVC, "_get_authorized_monitor_instances") as auth:
        auth.return_value = MonitorInstance.objects.none()
        with pytest.raises(UnauthorizedException):
            SVC._get_authorized_collect_configs([cfg.id], _ctx())


def test_ensure_instance_access_missing_and_denied():
    with pytest.raises(BaseAppException, match="监控实例不存在"):
        SVC._ensure_instance_access("missing")
    obj = MonitorObject.objects.create(name="EnsObj-auth", level="base")
    inst = MonitorInstance.objects.create(id="('ens',)", name="e", monitor_object=obj)
    assert SVC._ensure_instance_access(inst.id).id == inst.id
    assert SVC._ensure_instance_access(inst.id, _ctx(is_superuser=True)).id == inst.id
    with patch.object(SVC, "_get_authorized_monitor_instances") as auth:
        auth.return_value = MonitorInstance.objects.none()
        with pytest.raises(UnauthorizedException):
            SVC._ensure_instance_access(inst.id, _ctx())


def test_sanitize_instances_requires_node_ids_and_filters_groups():
    with pytest.raises(BaseAppException, match="缺少 node_ids"):
        SVC._sanitize_instances_for_onboarding(
            [{"instance_name": "x", "node_ids": []}],
            _ctx(is_superuser=True),
        )

    actor = _ctx()
    with (
        patch.object(SVC, "_get_actor_scope_groups", return_value=[1]),
        patch("apps.monitor.services.node_mgmt.NodeMgmt") as nm,
    ):
        nm.return_value.get_authorized_nodes_by_ids.return_value = [
            {"id": "n1", "organization_ids": [1, 9]},
        ]
        out = SVC._sanitize_instances_for_onboarding(
            [{"instance_id": "i1", "instance_name": "host", "node_ids": ["n1"]}],
            actor,
        )
    assert out[0]["group_ids"] == [1]
    assert out[0]["node_ids"] == ["n1"]

    with (
        patch.object(SVC, "_get_actor_scope_groups", return_value=[1]),
        patch("apps.monitor.services.node_mgmt.NodeMgmt") as nm,
    ):
        nm.return_value.get_authorized_nodes_by_ids.return_value = []
        with pytest.raises(UnauthorizedException, match="无权限节点"):
            SVC._sanitize_instances_for_onboarding(
                [{"instance_id": "i1", "node_ids": ["n-missing"]}],
                actor,
            )


def test_host_and_network_identity_adapters():
    assert SVC._should_use_host_identity_adapter("Host") is True
    assert SVC._should_use_host_identity_adapter("Pod") is False
    assert SVC._should_use_network_device_identity_adapter("Switch") is True
    assert SVC._should_use_network_device_identity_adapter("Host") is False

    hosts = SVC._prepare_host_identity_instances([{"instance_id": "10.0.0.1", "instance_name": "h1"}])
    assert hosts[0]["raw_instance_id"]
    assert hosts[0]["instance_id"] == hosts[0]["storage_instance_key"]

    devices = SVC._prepare_network_device_identity_instances(
        [{"instance_id": "1:default:10.1.1.1", "instance_name": "sw"}]
    )
    assert devices[0]["logical_instance_value"]
    with pytest.raises(ValueError, match="cloud_region and ip"):
        SVC._extract_network_device_identity_parts({"instance_id": "plain"})
