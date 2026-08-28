"""MonitorPluginService：复合对象名称抽取与维度归一化去重。"""
import pytest

from apps.monitor.services.plugin import MonitorPluginService

pytestmark = pytest.mark.unit


def test_extract_monitor_object_names_for_simple_and_compound():
    assert MonitorPluginService._extract_monitor_object_names({"name": "Host"}) == ["Host"]
    assert MonitorPluginService._extract_monitor_object_names({}) == []
    names = MonitorPluginService._extract_monitor_object_names(
        {
            "is_compound_object": True,
            "objects": [{"name": "CPU"}, {"name": ""}, {"name": "Mem"}, {}],
        }
    )
    assert names == ["CPU", "Mem"]


def test_normalize_metric_dimensions_dedupes_dicts_and_non_lists():
    assert MonitorPluginService.normalize_metric_dimensions(None) == []
    assert MonitorPluginService.normalize_metric_dimensions("cpu") == []
    dims = MonitorPluginService.normalize_metric_dimensions(
        [{"name": " cpu "}, {"name": "cpu"}, {"name": "mem", "type": "tag"}, "mem", "  "]
    )
    assert dims == [{"name": "cpu"}, {"name": "mem", "type": "tag"}]
