"""日志采集 Controller.controller：渲染模板后 bulk_create 并 RPC 下发。"""
from unittest.mock import patch

import pytest

from apps.log.models import CollectConfig, CollectInstance, CollectType
from apps.log.utils.plugin_controller import Controller

pytestmark = pytest.mark.django_db


def test_log_controller_renders_child_and_parent_templates(tmp_path, monkeypatch):
    collector = "Filebeat"
    collect_type = "logfile"
    template_dir = tmp_path / collector / collect_type
    template_dir.mkdir(parents=True)
    (template_dir / f"{collect_type}.base.yaml.j2").write_text("path={{ path }}", encoding="utf-8")
    (template_dir / f"{collect_type}.child.toml.j2").write_text("id={{ config_id }}", encoding="utf-8")

    collect_type_obj = CollectType.objects.create(
        name=collect_type, collector=collector, icon="i", description="", config_section="input"
    )
    CollectInstance.objects.create(id="log-inst-1", name="l1", collect_type=collect_type_obj, node_id="n1")

    monkeypatch.setattr("apps.log.utils.plugin_controller.PluginConstants.DIRECTORY", str(tmp_path))
    data = {
        "collect_type": collect_type,
        "collector": collector,
        "instances": [
            {
                "instance_id": "log-inst-1",
                "node_ids": ["n1"],
                "path": "/var/log/a.log",
                "ENV_TOKEN": "abc",
            }
        ],
        "configs": [{"path": "/var/log/a.log"}],
    }
    with patch("apps.log.utils.plugin_controller.NodeMgmt") as nm:
        nm.return_value.get_nodes_by_ids.return_value = [{"id": "n1", "operating_system": "linux"}]
        nm.return_value.cloudregion_tls_env_by_node_id.return_value = {"tls": "off"}
        nm.return_value.batch_create_configs_and_child_configs.return_value = None
        Controller(data).controller()

    created = list(CollectConfig.objects.filter(collect_instance_id="log-inst-1"))
    assert len(created) == 2
    assert {c.is_child for c in created} == {True, False}
    rpc = nm.return_value.batch_create_configs_and_child_configs
    rpc.assert_called_once()
    node_configs, child_configs = rpc.call_args.args
    assert len(node_configs) == 1
    assert "path=/var/log/a.log" in node_configs[0]["content"]
    assert len(child_configs) == 1
    assert child_configs[0]["config_section"] == "input"
    assert child_configs[0]["sort_order"] == 0
    env_key = next(iter(child_configs[0]["env_config"]))
    assert env_key.startswith("TOKEN__")
