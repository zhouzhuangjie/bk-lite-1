"""init_oid：已存在内置数据跳过；缺文件报错；force 重建。"""
import json

import pytest
from django.core.management import call_command

from apps.cmdb.models.collect_model import OidMapping

pytestmark = pytest.mark.django_db


def test_init_oid_skips_when_builtin_exists(capsys):
    OidMapping.objects.create(oid=".1.2.3", model="m", brand="b", device_type="switch", built_in=True)
    call_command("init_oid")
    assert OidMapping.objects.filter(built_in=True).exists()
    out = capsys.readouterr().out
    assert "跳过" in out


def test_init_oid_missing_file_raises(tmp_path, monkeypatch, capsys):
    OidMapping.objects.filter(built_in=True).delete()
    missing = str(tmp_path / "missing.json")
    monkeypatch.setattr(
        "apps.cmdb.management.commands.init_oid.os.path.join",
        lambda *a: missing,
    )
    with pytest.raises(FileNotFoundError, match="OID 文件不存在"):
        call_command("init_oid")


def test_init_oid_force_reloads_from_json(tmp_path, monkeypatch, capsys):
    OidMapping.objects.create(oid=".9.9.9", model="old", brand="old", device_type="switch", built_in=True)
    oid_file = tmp_path / "systemoid.json"
    oid_path = str(oid_file)
    oid_file.write_text(
        json.dumps(
            {
                "a": {"OID": ".1.3.6.1", "model": "X", "brand": "Huawei", "FirstTypeId": "Switch"},
                "b": {"OID": ".1.3.6.2", "model": "Y", "brand": "H3C", "FirstTypeId": "Router"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "apps.cmdb.management.commands.init_oid.os.path.join",
        lambda *a: oid_path,
    )
    monkeypatch.setattr(
        "apps.cmdb.management.commands.init_oid.os.path.exists",
        lambda p: p == oid_path,
    )
    call_command("init_oid", force=True)
    oids = set(OidMapping.objects.filter(built_in=True).values_list("oid", flat=True))
    assert oids == {".1.3.6.1", ".1.3.6.2"}
    switch = OidMapping.objects.get(oid=".1.3.6.1")
    assert switch.device_type == "switch"
    assert switch.brand == "Huawei"
