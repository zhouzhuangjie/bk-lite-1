"""gen_display_fields：从 supplementary_indicators 生成列；插入行。"""
import pytest

from apps.monitor.management.commands.gen_display_fields import (
    build_display_fields_for_object,
    insert_display_fields_lines,
)

pytestmark = pytest.mark.unit


def test_build_display_fields_skips_unknown_metrics():
    obj = {
        "metrics": [{"name": "cpu", "display_name": "CPU"}, {"name": "mem", "display_name": "内存"}],
        "supplementary_indicators": ["cpu", "missing", "mem"],
    }
    columns = build_display_fields_for_object(obj, "host")
    assert [c["name"] for c in columns] == ["CPU", "内存"]
    assert columns[0]["metrics"] == [{"plugin": "host", "metric": "cpu"}]
    assert columns[1]["sort_order"] == 2


def test_insert_display_fields_after_supplementary_array():
    text = '''{
  "plugin": "host",
  "supplementary_indicators": [
    "cpu"
  ],
  "metrics": []
}'''
    blocks = [[{"name": "CPU", "sort_order": 0, "metrics": [{"plugin": "host", "metric": "cpu"}]}]]
    out = insert_display_fields_lines(text, blocks)
    assert '"display_fields"' in out
    assert "CPU" in out
