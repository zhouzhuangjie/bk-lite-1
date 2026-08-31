"""MonitorPluginService：复合对象导入共享插件字段并挂 parent_id。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.monitor.services.plugin import MonitorPluginService

pytestmark = pytest.mark.unit


def test_import_compound_monitor_object_sets_parent_and_shared_fields():
    imported = []

    def fake_import(obj):
        imported.append(dict(obj))
        return SimpleNamespace(id=10 if obj.get("level") == "base" else 11)

    data = {
        "plugin": "host",
        "plugin_desc": "desc",
        "status_query": "up",
        "collector": "Telegraf",
        "collect_type": "host",
        "support_collect_detect": True,
        "node_selector": {"os": "linux"},
        "objects": [
            {"name": "Host", "level": "base"},
            {"name": "Disk", "level": "derivative"},
        ],
    }
    with patch.object(MonitorPluginService, "import_basic_monitor_object", side_effect=fake_import) as basic:
        MonitorPluginService.import_compound_monitor_object(data)
    assert basic.call_count == 2
    assert imported[0]["plugin"] == "host"
    assert imported[0]["collector"] == "Telegraf"
    assert imported[0]["collect_type"] == "host"
    assert imported[0]["support_collect_detect"] is True
    assert imported[0]["node_selector"] == {"os": "linux"}
    assert "parent_id" not in imported[0]
    assert imported[1]["name"] == "Disk"
    assert imported[1]["parent_id"] == 10
    assert imported[1]["plugin"] == "host"
