"""CustomSnmpPluginService：对象绑定、内置模板克隆与 initialize_templates。"""
import uuid

import pytest

from apps.core.exceptions.base_app_exception import BaseAppException
from apps.monitor.models import MonitorPlugin, MonitorPluginConfigTemplate, MonitorPluginUITemplate
from apps.monitor.models.monitor_object import MonitorObject
from apps.monitor.services.custom_snmp_plugin import (
    DEFAULT_CUSTOM_SNMP_COLLECT_SNIPPET,
    SNMP_COLLECT_MARKER_END,
    SNMP_COLLECT_MARKER_START,
    CustomSnmpPluginService,
)

pytestmark = pytest.mark.django_db

_CHILD = (
    "[[inputs.snmp]]\n"
    '  agents = ["udp://127.0.0.1:161"]\n'
    "\n"
    "[[inputs.snmp.field]]\n"
    '  oid = ".1.3.6.1.2.1.1.3.0"\n'
    '  name = "uptime"\n'
)


def _obj(name=None):
    return MonitorObject.objects.create(name=name or f"SnmpObj-{uuid.uuid4().hex[:6]}", level="base")


def test_get_monitor_object_requires_binding():
    plugin = MonitorPlugin.objects.create(name=f"snmp-unbound-{uuid.uuid4().hex[:6]}", collector="Telegraf", collect_type="snmp")
    with pytest.raises(BaseAppException, match="必须绑定一个监控对象"):
        CustomSnmpPluginService.get_monitor_object(plugin)
    obj = _obj()
    plugin.monitor_object.add(obj)
    assert CustomSnmpPluginService.get_monitor_object(plugin).id == obj.id


def test_get_builtin_plugin_missing_and_duplicate():
    obj = _obj()
    custom = MonitorPlugin.objects.create(
        name=f"snmp-custom-{uuid.uuid4().hex[:6]}",
        collector="Telegraf",
        collect_type="snmp",
        template_type="snmp",
    )
    custom.monitor_object.add(obj)
    with pytest.raises(BaseAppException, match="无可复用的 SNMP 内置模板"):
        CustomSnmpPluginService.get_builtin_plugin(custom)

    MonitorPlugin.objects.create(
        name=f"snmp-b1-{uuid.uuid4().hex[:6]}",
        collector="Telegraf",
        collect_type="snmp",
        template_type="builtin",
    ).monitor_object.add(obj)
    MonitorPlugin.objects.create(
        name=f"snmp-b2-{uuid.uuid4().hex[:6]}",
        collector="Telegraf",
        collect_type="snmp",
        template_type="builtin",
    ).monitor_object.add(obj)
    with pytest.raises(BaseAppException, match="多份 SNMP 内置模板"):
        CustomSnmpPluginService.get_builtin_plugin(custom)


def test_initialize_templates_clones_child_ui_and_plugin_fields():
    obj = _obj()
    builtin = MonitorPlugin.objects.create(
        name=f"snmp-src-{uuid.uuid4().hex[:6]}",
        collector="Telegraf",
        collect_type="snmp",
        template_type="builtin",
        status_query="up",
        description="src-desc",
        node_selector={"os": "linux"},
    )
    builtin.monitor_object.add(obj)
    MonitorPluginConfigTemplate.objects.create(
        plugin=builtin,
        type="collect",
        config_type="child",
        file_type="toml",
        content=_CHILD,
    )
    MonitorPluginConfigTemplate.objects.create(
        plugin=builtin,
        type="collect",
        config_type="parent",
        file_type="toml",
        content="parent-body",
    )
    MonitorPluginUITemplate.objects.create(plugin=builtin, content={"fields": ["uptime"]})

    target = MonitorPlugin.objects.create(
        name=f"snmp-dst-{uuid.uuid4().hex[:6]}",
        collector="Telegraf",
        collect_type="snmp",
        template_type="snmp",
    )
    target.monitor_object.add(obj)
    CustomSnmpPluginService.initialize_templates(target)
    target.refresh_from_db()
    assert target.status_query == "up"
    assert target.description == "src-desc"
    assert target.node_selector == {"os": "linux"}

    child = MonitorPluginConfigTemplate.objects.get(plugin=target, config_type="child")
    assert SNMP_COLLECT_MARKER_START in child.content
    assert SNMP_COLLECT_MARKER_END in child.content
    assert DEFAULT_CUSTOM_SNMP_COLLECT_SNIPPET in child.content
    parent = MonitorPluginConfigTemplate.objects.get(plugin=target, config_type="parent")
    assert parent.content == "parent-body"
    ui = MonitorPluginUITemplate.objects.get(plugin=target)
    assert ui.content == {"fields": ["uptime"]}
