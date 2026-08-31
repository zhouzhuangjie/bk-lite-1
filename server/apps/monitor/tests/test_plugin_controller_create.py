"""监控采集控制器：输入守卫、配置展开与模板渲染后落库。"""
from unittest.mock import patch

import pytest

from apps.core.exceptions.base_app_exception import BaseAppException
from apps.monitor.models import CollectConfig, MonitorInstance, MonitorObject, MonitorPlugin, MonitorPluginConfigTemplate
from apps.monitor.utils.plugin_controller import Controller

pytestmark = pytest.mark.django_db


def test_format_configs_skips_nodes_and_requires_fields():
    with pytest.raises(ValueError, match="缺少必需的字段"):
        Controller({"collect_type": "host"}).format_configs()

    data = {
        "collect_type": "host",
        "collector": "Telegraf",
        "instances": [
            {"instance_id": "a", "node_ids": [], "ip": "1.1.1.1"},
            {"instance_id": "b", "node_ids": ["n1"], "ip": "2.2.2.2"},
        ],
        "configs": [{"type": "base", "interval": "10s"}],
    }
    original_empty = data["instances"][0]["node_ids"]
    out = Controller(data).format_configs()
    assert original_empty == []
    assert len(out) == 1
    assert out[0]["instance_id"] == "b"
    assert out[0]["node_id"] == "n1"
    assert out[0]["type"] == "base"
    assert out[0]["ip"] == "2.2.2.2"


def test_controller_rejects_empty_missing_template_and_missing_type():
    with pytest.raises(ValueError, match="不能为空"):
        Controller({}).controller()
    with pytest.raises(ValueError, match="缺少必需字段"):
        Controller({"collector": "Telegraf"}).controller()

    plugin = MonitorPlugin.objects.create(name="pc-empty", collector="Telegraf", collect_type="host")
    with pytest.raises(BaseAppException, match="未找到采集模板"):
        Controller(
            {
                "collector": "Telegraf",
                "collect_type": "host",
                "monitor_plugin_id": plugin.id,
                "instances": [{"instance_id": "x", "node_ids": ["n1"]}],
                "configs": [{"type": "base"}],
            }
        ).controller()

    MonitorPluginConfigTemplate.objects.create(
        plugin=plugin, type="base", config_type="base", file_type="toml", content="ip={{ ip }}"
    )
    with pytest.raises(BaseAppException, match="没有可创建的采集配置"):
        Controller(
            {
                "collector": "Telegraf",
                "collect_type": "host",
                "monitor_plugin_id": plugin.id,
                "instances": [{"instance_id": "x", "node_ids": []}],
                "configs": [{"type": "base"}],
            }
        ).controller()

    with pytest.raises(BaseAppException, match="缺少 type"):
        Controller(
            {
                "collector": "Telegraf",
                "collect_type": "host",
                "monitor_plugin_id": plugin.id,
                "instances": [{"instance_id": "x", "node_ids": ["n1"], "ip": "1.1.1.1"}],
                "configs": [{"interval": "10s"}],
            }
        ).controller()


def test_controller_renders_and_creates_collect_config():
    obj = MonitorObject.objects.create(name="Host-pc-ctrl")
    MonitorInstance.objects.create(id="inst-pc-1", name="i1", monitor_object=obj)
    plugin = MonitorPlugin.objects.create(
        name="pc-ok",
        collector="Telegraf",
        collect_type="host",
        template_id="tpl-pc",
    )
    MonitorPluginConfigTemplate.objects.create(
        plugin=plugin,
        type="base",
        config_type="base",
        file_type="toml",
        content="ip={{ ip }}",
    )
    data = {
        "collector": "Telegraf",
        "collect_type": "host",
        "monitor_plugin_id": plugin.id,
        "instances": [
            {
                "instance_id": "inst-pc-1",
                "ip": "10.0.0.8",
                "node_ids": ["node-a"],
                "ENV_TOKEN": "secret",
            }
        ],
        "configs": [{"type": "base"}],
    }
    with patch("apps.monitor.utils.plugin_controller.NodeMgmt") as nm:
        nm.return_value.batch_create_configs_and_child_configs.return_value = None
        Controller(data).controller()
    configs = list(CollectConfig.objects.filter(monitor_instance_id="inst-pc-1"))
    assert len(configs) == 1
    assert configs[0].is_child is False
    assert configs[0].config_type == "base"
    rpc = nm.return_value.batch_create_configs_and_child_configs
    rpc.assert_called_once()
    node_configs, child_configs = rpc.call_args.args
    assert len(node_configs) == 1
    assert "ip=10.0.0.8" in node_configs[0]["content"]
    assert node_configs[0]["env_config"] == {"TOKEN": "secret"}
    assert child_configs == []
