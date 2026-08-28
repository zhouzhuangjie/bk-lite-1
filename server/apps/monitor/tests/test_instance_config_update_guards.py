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


def test_update_instance_config_converts_yaml_toml_and_delegates(monkeypatch):
    from unittest.mock import patch

    base = MagicMock(id="base-1", monitor_instance_id="inst-a")
    child = MagicMock(id="child-1", monitor_instance_id="inst-a")
    monkeypatch.setattr(
        InstanceConfigService,
        "_get_authorized_collect_configs",
        lambda ids, actor, require_operate=True: [base, child],
    )
    node_mgmt = MagicMock()
    with (
        patch("apps.monitor.services.node_mgmt.NodeMgmt", return_value=node_mgmt),
        patch("apps.monitor.services.node_mgmt.ConfigFormat.json_to_yaml", return_value="yaml-out") as to_yaml,
        patch("apps.monitor.services.node_mgmt.ConfigFormat.json_to_toml", return_value="toml-out") as to_toml,
    ):
        InstanceConfigService.update_instance_config(
            {"id": "child-1", "content": {"k": 1}, "env_config": {"e": 1}},
            {"id": "base-1", "content": {"b": 2}, "env_config": {"e": 2}},
        )
    to_yaml.assert_called_once_with({"b": 2})
    to_toml.assert_called_once_with({"k": 1})
    node_mgmt.update_config_content.assert_called_once_with("base-1", "yaml-out", {"e": 2})
    node_mgmt.update_child_config_content.assert_called_once_with("child-1", "toml-out", {"e": 1})


def test_update_instance_config_skips_missing_child(monkeypatch):
    from unittest.mock import patch

    base = MagicMock(id="base-1", monitor_instance_id="inst-a")
    monkeypatch.setattr(
        InstanceConfigService,
        "_get_authorized_collect_configs",
        lambda ids, actor, require_operate=True: [base],
    )
    node_mgmt = MagicMock()
    with (
        patch("apps.monitor.services.node_mgmt.NodeMgmt", return_value=node_mgmt),
        patch("apps.monitor.services.node_mgmt.ConfigFormat.json_to_yaml", return_value="yaml-out"),
        patch("apps.monitor.services.node_mgmt.ConfigFormat.json_to_toml") as to_toml,
    ):
        InstanceConfigService.update_instance_config(
            {"id": "child-missing", "content": {"k": 1}},
            {"id": "base-1", "content": {"b": 2}},
        )
    node_mgmt.update_config_content.assert_called_once_with("base-1", "yaml-out", None)
    to_toml.assert_not_called()
    node_mgmt.update_child_config_content.assert_not_called()
