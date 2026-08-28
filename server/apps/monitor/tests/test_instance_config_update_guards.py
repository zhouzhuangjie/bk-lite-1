"""InstanceConfigService：空实例不建规则；配置跨实例拒绝。"""
from unittest.mock import MagicMock

import pytest

from apps.core.exceptions.base_app_exception import BaseAppException
from apps.monitor.models.monitor_object import MonitorObject
from apps.monitor.services.node_mgmt import InstanceConfigService

pytestmark = pytest.mark.django_db


def test_batch_create_default_rules_empty_instances_or_no_children():
    obj = MonitorObject.objects.create(name="CfgParent", level="base")
    assert InstanceConfigService._batch_create_default_rules([], obj.id) == []
    assert InstanceConfigService._batch_create_default_rules(
        [{"instance_id": "h1", "group_ids": [1]}], obj.id
    ) == []


def test_update_instance_config_rejects_mismatched_instance(monkeypatch):
    base = MagicMock(id="base-1", monitor_instance_id="inst-a")
    child = MagicMock(id="child-1", monitor_instance_id="inst-b")
    monkeypatch.setattr(
        InstanceConfigService,
        "_get_authorized_collect_configs",
        lambda ids, actor, require_operate=True: [base, child],
    )
    with pytest.raises(BaseAppException, match="不属于同一监控实例"):
        InstanceConfigService.update_instance_config(
            {"id": "child-1", "content": {}, "env_config": {}},
            {"id": "base-1", "content": {}, "env_config": {}},
        )
