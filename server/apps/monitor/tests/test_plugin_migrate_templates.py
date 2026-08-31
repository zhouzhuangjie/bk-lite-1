"""插件迁移：模板同步、远程模块替换、清理与批量保存契约。"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.monitor.management.services import plugin_migrate
from apps.monitor.models import CollectConfig, MetricGroup, MonitorObject, MonitorPlugin
from apps.monitor.models.monitor_object import MonitorInstance
from apps.monitor.models.plugin import MonitorPluginConfigTemplate, MonitorPluginUITemplate

pytestmark = pytest.mark.django_db


def _plugin(name="Vendor SNMP R13"):
    return MonitorPlugin.objects.create(name=name, display_name=name, is_pre=True)


# --------------------------------------------------------------------------
# _validate_template_identity
# --------------------------------------------------------------------------


def test_validate_template_identity_skips_dir_and_templated_collect_type(tmp_path):
    plugin_dir = tmp_path / "p"
    plugin_dir.mkdir()
    skipped_dir = plugin_dir / "dir.j2"
    skipped_dir.mkdir()
    templated = plugin_dir / "ok.j2"
    templated.write_text('collect_type = "{{ collect_type }}"\n', encoding="utf-8")
    read_paths = []
    real_read = Path.read_text

    def _read(self, *a, **k):
        read_paths.append(self)
        return real_read(self, *a, **k)

    with patch.object(Path, "read_text", _read):
        assert plugin_migrate._validate_template_identity(plugin_dir, "snmp") is None
    assert all(getattr(p, "name", None) != "dir.j2" for p in read_paths)
    assert any(getattr(p, "name", None) == "ok.j2" for p in read_paths)

    dir_only = tmp_path / "only-dir"
    dir_only.mkdir()
    (dir_only / "nested.j2").mkdir()
    assert plugin_migrate._validate_template_identity(dir_only, "snmp") is None


def test_validate_template_identity_rejects_literal_mismatch(tmp_path):
    plugin_dir = tmp_path / "p"
    plugin_dir.mkdir()
    j2 = plugin_dir / "bad.j2"
    j2.write_text('collect_type = "other"\n', encoding="utf-8")
    with pytest.raises(plugin_migrate.PluginIdentityValidationError, match="collect_type mismatch"):
        plugin_migrate._validate_template_identity(plugin_dir, "snmp")


# --------------------------------------------------------------------------
# _replace_remote_host_metrics_modules_line / _sync_remote_host_metrics_modules
# --------------------------------------------------------------------------


def test_replace_remote_host_metrics_modules_line_non_string_and_unchanged():
    assert plugin_migrate._replace_remote_host_metrics_modules_line(None) == (None, False)
    csv = plugin_migrate.REMOTE_HOST_METRICS_MODULES_CSV
    content = f'metrics_modules = "{csv}"'
    updated, changed = plugin_migrate._replace_remote_host_metrics_modules_line(content)
    assert changed is False
    assert updated == content
    updated, changed = plugin_migrate._replace_remote_host_metrics_modules_line('metrics_modules = "cpu"')
    assert changed is True
    assert csv in updated


def test_sync_remote_host_metrics_modules_paths(monkeypatch):
    assert plugin_migrate._sync_remote_host_metrics_modules() == 0

    obj = MonitorObject.objects.create(name="HostR13", display_name="HostR13")
    inst = MonitorInstance.objects.create(id="('host-r13',)", name="h", monitor_object=obj)
    CollectConfig.objects.create(
        id="child-r13",
        monitor_instance=inst,
        collector="Telegraf",
        collect_type="http",
        config_type="host",
        file_type="toml",
        is_child=True,
    )

    node = MagicMock()
    node.get_child_configs_by_ids.side_effect = RuntimeError("rpc down")
    monkeypatch.setattr(plugin_migrate, "NodeMgmt", lambda: node)
    assert plugin_migrate._sync_remote_host_metrics_modules() == 0

    node = MagicMock()
    node.get_child_configs_by_ids.return_value = [
        {"id": None, "content": 'metrics_modules = "cpu"'},
        {"id": "child-r13", "content": 'metrics_modules = "cpu"'},
        {"id": "child-skip", "content": f'metrics_modules = "{plugin_migrate.REMOTE_HOST_METRICS_MODULES_CSV}"'},
    ]

    def update(config_id, content):
        if config_id == "child-r13":
            raise RuntimeError("update fail")

    node.update_child_config_content.side_effect = update
    monkeypatch.setattr(plugin_migrate, "NodeMgmt", lambda: node)
    # 更新失败计 0
    assert plugin_migrate._sync_remote_host_metrics_modules() == 0

    node = MagicMock()
    node.get_child_configs_by_ids.return_value = [
        {"id": "child-r13", "content": 'metrics_modules = "cpu"'},
    ]
    monkeypatch.setattr(plugin_migrate, "NodeMgmt", lambda: node)
    assert plugin_migrate._sync_remote_host_metrics_modules() == 1
    node.update_child_config_content.assert_called_once()


# --------------------------------------------------------------------------
# _process_config_templates / _process_ui_templates
# --------------------------------------------------------------------------


def test_process_config_templates_create_update_delete_and_skip(tmp_path):
    plugin = _plugin("Tpl Plugin")
    plugin_dir = tmp_path / "tpl"
    plugin_dir.mkdir()
    (plugin_dir / "not-a-file.j2").mkdir()
    (plugin_dir / "badname.j2").write_text("x", encoding="utf-8")
    (plugin_dir / "cpu.child.toml.j2").write_text("NEW", encoding="utf-8")
    (plugin_dir / "mem.child.toml.j2").write_text("MEM", encoding="utf-8")
    (plugin_dir / "boom.child.toml.j2").write_text("x", encoding="utf-8")

    existing = MonitorPluginConfigTemplate.objects.create(
        plugin=plugin, type="cpu", config_type="child", file_type="toml", content="OLD",
    )
    stale = MonitorPluginConfigTemplate.objects.create(
        plugin=plugin, type="disk", config_type="child", file_type="toml", content="STALE",
    )
    db_templates = {
        ("cpu", "child", "toml"): existing,
        ("disk", "child", "toml"): stale,
    }

    real_read = Path.read_text

    def _read(self, *a, **k):
        if self.name == "boom.child.toml.j2":
            raise OSError("read fail")
        return real_read(self, *a, **k)

    with patch.object(Path, "read_text", _read):
        to_create, to_update, to_delete = plugin_migrate._process_config_templates(plugin_dir, plugin, db_templates)

    assert [tpl.type for tpl in to_create] == ["mem"]
    assert to_update == [existing]
    assert existing.content == "NEW"
    assert to_delete == [stale]


def test_process_ui_templates_create_update_delete_and_invalid(tmp_path):
    plugin = _plugin("UI Plugin")
    plugin_dir = tmp_path / "ui"
    plugin_dir.mkdir()

    to_create, to_update, to_delete = plugin_migrate._process_ui_templates(plugin_dir, plugin, None)
    assert to_create == to_update == to_delete == []

    db_ui = MonitorPluginUITemplate.objects.create(plugin=plugin, content={"old": 1})
    to_create, to_update, to_delete = plugin_migrate._process_ui_templates(plugin_dir, plugin, db_ui)
    assert to_delete == [db_ui]

    (plugin_dir / "UI.json").write_text("{bad", encoding="utf-8")
    to_create, to_update, to_delete = plugin_migrate._process_ui_templates(plugin_dir, plugin, db_ui)
    assert to_create == to_update == to_delete == []

    (plugin_dir / "UI.json").write_text(json.dumps({"new": 1}), encoding="utf-8")
    to_create, to_update, to_delete = plugin_migrate._process_ui_templates(plugin_dir, plugin, db_ui)
    assert to_update == [db_ui]
    assert db_ui.content == {"new": 1}

    other = _plugin("UI Plugin 2")
    to_create, to_update, to_delete = plugin_migrate._process_ui_templates(plugin_dir, other, None)
    assert len(to_create) == 1
    assert to_create[0].content == {"new": 1}


# --------------------------------------------------------------------------
# _collect_templates_to_process / _batch_save_templates
# --------------------------------------------------------------------------


def test_collect_templates_skips_missing_plugin_and_bad_json(tmp_path):
    plugin = _plugin("Collect P")
    good_dir = tmp_path / "g"
    good_dir.mkdir()
    metrics = good_dir / "metrics.json"
    metrics.write_text(json.dumps({"plugin": plugin.name}), encoding="utf-8")
    (good_dir / "cpu.child.toml.j2").write_text("C", encoding="utf-8")
    (good_dir / "UI.json").write_text(json.dumps({"u": 1}), encoding="utf-8")

    missing = tmp_path / "m" / "metrics.json"
    missing.parent.mkdir()
    missing.write_text(json.dumps({"plugin": "NoSuch"}), encoding="utf-8")
    bad = tmp_path / "b" / "metrics.json"
    bad.parent.mkdir()
    bad.write_text("{", encoding="utf-8")

    data = plugin_migrate._collect_templates_to_process(
        [str(metrics), str(missing), str(bad)],
        {plugin.name: plugin},
        {},
        {},
    )
    assert len(data["config"][0]) == 1
    assert len(data["ui"][0]) == 1


def test_batch_save_templates_create_update_delete():
    plugin = _plugin("Batch P")
    create_cfg = MonitorPluginConfigTemplate(
        plugin=plugin, type="cpu", config_type="child", file_type="toml", content="c",
    )
    update_cfg = MonitorPluginConfigTemplate.objects.create(
        plugin=plugin, type="mem", config_type="child", file_type="toml", content="old",
    )
    update_cfg.content = "new"
    delete_cfg = MonitorPluginConfigTemplate.objects.create(
        plugin=plugin, type="disk", config_type="child", file_type="toml", content="gone",
    )
    create_ui = MonitorPluginUITemplate(plugin=plugin, content={"a": 1})
    # 另建一个已存在 UI 以便更新/删除走不同插件
    other = _plugin("Batch P2")
    update_ui = MonitorPluginUITemplate.objects.create(plugin=other, content={"old": 1})
    update_ui.content = {"new": 1}
    third = _plugin("Batch P3")
    delete_ui = MonitorPluginUITemplate.objects.create(plugin=third, content={"x": 1})

    stats = plugin_migrate._batch_save_templates(
        {
            "config": ([create_cfg], [update_cfg], [delete_cfg]),
            "ui": ([create_ui], [update_ui], [delete_ui]),
        }
    )
    assert stats["config_create"] == 1
    assert stats["config_update"] == 1
    assert stats["config_delete"] == 1
    assert stats["ui_create"] == 1
    assert stats["ui_update"] == 1
    assert stats["ui_delete"] == 1
    assert MonitorPluginConfigTemplate.objects.filter(plugin=plugin, type="cpu").exists()
    assert MonitorPluginConfigTemplate.objects.get(pk=update_cfg.pk).content == "new"
    assert not MonitorPluginConfigTemplate.objects.filter(pk=delete_cfg.pk).exists()
    assert MonitorPluginUITemplate.objects.get(pk=update_ui.pk).content == {"new": 1}
    assert not MonitorPluginUITemplate.objects.filter(pk=delete_ui.pk).exists()


# --------------------------------------------------------------------------
# cleanup
# --------------------------------------------------------------------------


def test_cleanup_removed_plugins_and_read_error(tmp_path):
    keep = _plugin("Keep Builtin")
    drop = _plugin("Drop Builtin")
    custom = MonitorPlugin.objects.create(name="Custom Not Pre", display_name="c", is_pre=False)
    metrics = tmp_path / "metrics.json"
    metrics.write_text(json.dumps({"plugin": keep.name}), encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    plugin_migrate._cleanup_removed_plugins([str(metrics), str(bad)])
    assert MonitorPlugin.objects.filter(pk=keep.pk).exists()
    assert not MonitorPlugin.objects.filter(pk=drop.pk).exists()
    assert MonitorPlugin.objects.filter(pk=custom.pk).exists()


def test_cleanup_orphan_objects_and_empty_metric_groups():
    orphan = MonitorObject.objects.create(name="OrphanR13", display_name="o")
    kept = MonitorObject.objects.create(name="KeptR13", display_name="k")
    plugin = _plugin("Keep For Object")
    plugin.monitor_object.add(kept)
    plugin_migrate._cleanup_orphan_objects()
    assert not MonitorObject.objects.filter(pk=orphan.pk).exists()
    assert MonitorObject.objects.filter(pk=kept.pk).exists()

    empty = MetricGroup.objects.create(name="EmptyG", monitor_object=kept, is_pre=True)
    plugin_migrate._cleanup_empty_builtin_metric_groups()
    assert not MetricGroup.objects.filter(pk=empty.pk).exists()
