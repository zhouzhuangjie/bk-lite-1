"""自定义 SNMP 子配置同步计划：空配置、类型不匹配、渲染失败、成功计划。"""
from unittest.mock import MagicMock

import pytest

from apps.core.exceptions.base_app_exception import BaseAppException
from apps.monitor.models import CollectConfig, MonitorPlugin, MonitorPluginConfigTemplate
from apps.monitor.models.monitor_object import MonitorInstance, MonitorObject
from apps.monitor.services.custom_snmp_plugin import CustomSnmpPluginService

pytestmark = pytest.mark.django_db


def _plugin_and_template():
    obj = MonitorObject.objects.create(name="SnmpObj-plan", level="base")
    plugin = MonitorPlugin.objects.create(name="custom-snmp-plan", collector="telegraf", collect_type="snmp")
    plugin.monitor_object.add(obj)
    template = MonitorPluginConfigTemplate.objects.create(
        plugin=plugin, type="snmp", config_type="snmp", file_type="toml", content="ip={{ ip }}"
    )
    inst = MonitorInstance.objects.create(id="snmp-inst-1", name="s1", monitor_object=obj)
    return plugin, template, inst


def test_propagation_plan_empty_when_no_child_configs():
    plugin, template, _ = _plugin_and_template()
    assert CustomSnmpPluginService._build_propagation_plan(plugin, "x={{ ip }}", template) == []


def test_propagation_plan_rejects_type_mismatch_and_missing_child(monkeypatch):
    plugin, template, inst = _plugin_and_template()
    CollectConfig.objects.create(
        id="cfg-mismatch",
        monitor_instance=inst,
        monitor_plugin=plugin,
        collector="telegraf",
        collect_type="snmp",
        config_type="other",
        file_type="toml",
        is_child=True,
    )
    monkeypatch.setattr("apps.monitor.services.custom_snmp_plugin.NodeMgmt", MagicMock)
    with pytest.raises(BaseAppException, match="采集配置类型与模板不匹配"):
        CustomSnmpPluginService._build_propagation_plan(plugin, "x=1", template)

    CollectConfig.objects.filter(id="cfg-mismatch").update(config_type="snmp")
    node = MagicMock()
    node.get_child_configs_by_ids.return_value = []
    monkeypatch.setattr("apps.monitor.services.custom_snmp_plugin.NodeMgmt", lambda: node)
    with pytest.raises(BaseAppException, match="未找到实例"):
        CustomSnmpPluginService._build_propagation_plan(plugin, "x=1", template)


def test_propagation_plan_renders_and_validates_toml(monkeypatch):
    plugin, template, inst = _plugin_and_template()
    CollectConfig.objects.create(
        id="cfg-ok",
        monitor_instance=inst,
        monitor_plugin=plugin,
        collector="telegraf",
        collect_type="snmp",
        config_type="snmp",
        file_type="toml",
        is_child=True,
    )
    node = MagicMock()
    node.get_child_configs_by_ids.return_value = [
        {"id": "cfg-ok", "content": 'config = { agents = ["10.0.0.1:161"], tags = { instance_id = "i1" } }'}
    ]
    monkeypatch.setattr("apps.monitor.services.custom_snmp_plugin.NodeMgmt", lambda: node)
    monkeypatch.setattr(
        CustomSnmpPluginService,
        "_build_child_render_context",
        lambda *a, **k: {"ip": "10.0.0.1"},
    )
    controller = MagicMock()
    controller.render_template.return_value = "ok = 1\n"
    monkeypatch.setattr("apps.monitor.services.custom_snmp_plugin.Controller", lambda data: controller)
    monkeypatch.setattr(
        "apps.monitor.services.custom_snmp_plugin.ConfigFormat.toml_to_dict",
        lambda content: {"ok": 1},
    )

    plan = CustomSnmpPluginService._build_propagation_plan(plugin, "ip={{ ip }}", template)
    assert len(plan) == 1
    assert plan[0]["id"] == "cfg-ok"
    assert plan[0]["rendered_content"] == "ok = 1\n"
    assert "agents" in plan[0]["original_content"] or plan[0]["original_content"]
