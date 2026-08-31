"""init_algorithm_config：缺目录、非法 JSON/字段、创建与已存在跳过。"""
import json
from io import StringIO

import pytest
from django.core.management import call_command

from apps.mlops.management.commands import init_algorithm_config as cmd_mod
from apps.mlops.management.commands.init_algorithm_config import Command
from apps.mlops.models import AlgorithmConfig

pytestmark = pytest.mark.django_db


def test_load_and_validate_file_rejects_invalid_payloads(tmp_path):
    cmd = Command()
    broken = tmp_path / "x.json"
    broken.write_text("{", encoding="utf-8")
    ok, payload, reason = cmd._load_and_validate_file(broken)
    assert ok is False
    assert payload == {}
    assert reason.startswith("JSON 解析失败")

    broken.write_text("[]", encoding="utf-8")
    ok, _, reason = cmd._load_and_validate_file(broken)
    assert ok is False
    assert reason == "顶层必须是对象"

    broken.write_text(json.dumps({"name": "x"}), encoding="utf-8")
    ok, _, reason = cmd._load_and_validate_file(broken)
    assert "缺少字段" in reason

    extra = {
        "name": "x",
        "display_name": "X",
        "image": "img",
        "scenario_description": "s",
        "form_config": {},
        "extra": 1,
    }
    broken.write_text(json.dumps(extra), encoding="utf-8")
    ok, _, reason = cmd._load_and_validate_file(broken)
    assert "多余字段: extra" in reason

    bad_form = {
        "name": "x",
        "display_name": "X",
        "image": "img",
        "scenario_description": "s",
        "form_config": [],
    }
    (tmp_path / "x.json").write_text(json.dumps(bad_form), encoding="utf-8")
    ok, _, reason = cmd._load_and_validate_file(tmp_path / "x.json")
    assert reason == "form_config 必须是对象"

    not_str = {
        "name": 1,
        "display_name": "X",
        "image": "img",
        "scenario_description": "s",
        "form_config": {},
    }
    (tmp_path / "x.json").write_text(json.dumps(not_str), encoding="utf-8")
    ok, _, reason = cmd._load_and_validate_file(tmp_path / "x.json")
    assert reason == "name 必须是字符串"

    empty_name = {
        "name": "  ",
        "display_name": "X",
        "image": "img",
        "scenario_description": "s",
        "form_config": {},
    }
    (tmp_path / "x.json").write_text(json.dumps(empty_name), encoding="utf-8")
    ok, _, reason = cmd._load_and_validate_file(tmp_path / "x.json")
    assert reason == "name 不能为空字符串"

    mismatch = {
        "name": "other",
        "display_name": "X",
        "image": "img",
        "scenario_description": "s",
        "form_config": {},
    }
    (tmp_path / "ECOD.json").write_text(json.dumps(mismatch), encoding="utf-8")
    ok, _, reason = cmd._load_and_validate_file(tmp_path / "ECOD.json")
    assert reason == "name 必须与文件名 stem 完全一致"


def test_handle_missing_root_and_mixed_files(tmp_path, monkeypatch):
    class DummyPath:
        def __init__(self, *a, **k):
            pass

        def resolve(self):
            return self

        @property
        def parents(self):
            return _Parents()

    class _Parents:
        def __getitem__(self, idx):
            return tmp_path

    monkeypatch.setattr(cmd_mod, "Path", DummyPath)
    stdout = StringIO()
    call_command("init_algorithm_config", stdout=stdout)
    out = stdout.getvalue()
    assert "未找到算法配置目录" in out
    assert "created=0" in out
    assert "skipped_invalid=0" in out

    cfg = tmp_path / "support-files" / "algorithm-configs"
    cfg.mkdir(parents=True)
    (cfg / "notes.txt").write_text("skip-file", encoding="utf-8")
    (cfg / "not_a_type").mkdir()
    ad = cfg / "anomaly_detection"
    ad.mkdir()
    (ad / "readme.txt").write_text("skip", encoding="utf-8")
    (ad / "bad.json").write_text("{", encoding="utf-8")
    existing_payload = {
        "name": "EXISTING",
        "display_name": "Exist",
        "image": "img:old",
        "scenario_description": "s",
        "form_config": {"k": 1},
    }
    (ad / "EXISTING.json").write_text(json.dumps(existing_payload), encoding="utf-8")
    AlgorithmConfig.objects.create(
        algorithm_type="anomaly_detection",
        name="EXISTING",
        display_name="Exist",
        image="img:old",
        scenario_description="s",
        form_config={"k": 1},
    )
    new_payload = {
        "name": "NEWALG",
        "display_name": "New",
        "image": "img:new",
        "scenario_description": "desc",
        "form_config": {"fields": []},
    }
    (ad / "NEWALG.json").write_text(json.dumps(new_payload), encoding="utf-8")

    stdout = StringIO()
    stderr = StringIO()
    call_command("init_algorithm_config", stdout=stdout, stderr=stderr)
    out = stdout.getvalue()
    err = stderr.getvalue()
    assert "已创建: anomaly_detection/NEWALG" in out
    assert "已存在，跳过: anomaly_detection/EXISTING" in out
    assert "无效配置" in err
    assert AlgorithmConfig.objects.filter(algorithm_type="anomaly_detection", name="NEWALG").exists()
    created = AlgorithmConfig.objects.get(algorithm_type="anomaly_detection", name="NEWALG")
    assert created.display_name == "New"
    assert created.image == "img:new"
    assert created.form_config == {"fields": []}
