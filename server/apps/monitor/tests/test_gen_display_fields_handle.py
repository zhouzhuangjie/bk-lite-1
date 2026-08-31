"""gen_display_fields 命令：跳过已有 display_fields、空块，以及写入新文件。"""
from django.core.management import call_command

pytestmark = __import__("pytest").mark.unit


def test_handle_skips_existing_empty_and_writes_needed(tmp_path, monkeypatch):
    skip = tmp_path / "skip.json"
    skip.write_text(
        '{\n  "plugin": "p",\n  "display_fields": [],\n  "supplementary_indicators": ["cpu"],\n'
        '  "metrics": [{"name": "cpu", "display_name": "CPU"}]\n}\n',
        encoding="utf-8",
    )
    empty = tmp_path / "empty.json"
    empty.write_text(
        '{\n  "plugin": "p",\n  "supplementary_indicators": [],\n  "metrics": []\n}\n',
        encoding="utf-8",
    )
    need = tmp_path / "need.json"
    need.write_text(
        '{\n  "plugin": "p",\n  "supplementary_indicators": ["cpu"],\n'
        '  "metrics": [{"name": "cpu", "display_name": "CPU"}]\n}\n',
        encoding="utf-8",
    )

    calls = {"n": 0}

    def fake_find(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return [str(skip), str(empty), str(need)]
        return []

    monkeypatch.setattr(
        "apps.monitor.management.commands.gen_display_fields.find_files_by_pattern",
        fake_find,
    )
    call_command("gen_display_fields")
    assert '"display_fields"' in skip.read_text(encoding="utf-8")
    assert '"display_fields"' not in empty.read_text(encoding="utf-8")
    written = need.read_text(encoding="utf-8")
    assert '"display_fields"' in written
    assert "CPU" in written
