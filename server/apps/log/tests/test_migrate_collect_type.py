"""migrate_collect_type：从插件目录同步 CollectType，并删除目录中已不存在的记录。"""
import json

import pytest

from apps.log.management.services.plugin import migrate_collect_type
from apps.log.models import CollectType

pytestmark = pytest.mark.django_db


def test_migrate_collect_type_upserts_and_deletes_stale(tmp_path, monkeypatch):
    collector = "Filebeat"
    collect_dir = tmp_path / collector / "logfile"
    collect_dir.mkdir(parents=True)
    (tmp_path / collector / "readme.txt").write_text("ignore", encoding="utf-8")
    payload = {
        "name": "logfile",
        "collector": collector,
        "icon": "log",
        "description": "file log",
        "default_query": "*",
        "attrs": [],
    }
    (collect_dir / "collect_type.json").write_text(json.dumps(payload), encoding="utf-8")
    (collect_dir / "logfile.base.yaml.j2").write_text("x", encoding="utf-8")
    CollectType.objects.create(name="stale", collector="Filebeat", icon="x", description="old")
    monkeypatch.setattr("apps.log.management.services.plugin.PluginConstants.DIRECTORY", str(tmp_path))
    migrate_collect_type()
    created = CollectType.objects.get(name="logfile", collector="Filebeat")
    assert created.icon == "log"
    assert created.description == "file log"
    assert not CollectType.objects.filter(name="stale", collector="Filebeat").exists()
