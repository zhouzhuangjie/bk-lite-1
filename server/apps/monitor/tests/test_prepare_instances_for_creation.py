"""InstanceConfigService._prepare_instances_for_creation：ID 归一化、冲突拒绝、复用/恢复分类。"""
import pytest

from apps.core.exceptions.base_app_exception import BaseAppException
from apps.monitor.models import CollectConfig, MonitorInstance, MonitorObject, MonitorPlugin
from apps.monitor.services.node_mgmt import InstanceConfigService

pytestmark = pytest.mark.django_db


def test_prepare_instances_rewrites_ids_and_classifies():
    obj = MonitorObject.objects.create(name="Host-prep")
    plugin = MonitorPlugin.objects.create(name="prep-plugin", collector="Telegraf", collect_type="host")
    MonitorInstance.objects.create(id="keep-me", name="alive", monitor_object=obj, is_deleted=False)
    MonitorInstance.objects.create(id="gone-me", name="deleted", monitor_object=obj, is_deleted=True)

    instances = [
        {"instance_id": "raw-new", "instance_name": "n1", "storage_instance_key": "keep-me"},
        {"instance_id": "raw-gone", "instance_name": "n2", "storage_instance_key": "gone-me"},
        {"instance_id": "brand", "instance_name": "n3", "storage_instance_key": "brand-new"},
    ]
    new_instances, existing_instances, deleted_ids = InstanceConfigService._prepare_instances_for_creation(
        instances, obj.id, "host", "Telegraf", [{"type": "base"}]
    )
    assert instances[0]["instance_id"] == "keep-me"
    assert instances[1]["instance_id"] == "gone-me"
    assert instances[2]["instance_id"] == "brand-new"
    existing_ids = {i["instance_id"] for i in existing_instances}
    new_ids = {i["instance_id"] for i in new_instances}
    assert existing_ids == {"keep-me", "gone-me"}
    assert new_ids == {"brand-new"}
    assert deleted_ids == ["gone-me"]


def test_prepare_instances_rejects_existing_config_types():
    obj = MonitorObject.objects.create(name="Host-conflict")
    plugin = MonitorPlugin.objects.create(name="prep-conflict", collector="Telegraf", collect_type="host")
    inst = MonitorInstance.objects.create(id="conflict-1", name="c1", monitor_object=obj)
    CollectConfig.objects.create(
        id="cfg-1",
        monitor_instance=inst,
        monitor_plugin=plugin,
        collector="Telegraf",
        collect_type="host",
        config_type="base",
        file_type="toml",
        is_child=False,
    )
    with pytest.raises(BaseAppException, match="已存在采集配置"):
        InstanceConfigService._prepare_instances_for_creation(
            [{"instance_id": "x", "instance_name": "c1", "storage_instance_key": "conflict-1"}],
            obj.id,
            "host",
            "Telegraf",
            [{"type": "base"}],
        )
