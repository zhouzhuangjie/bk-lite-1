"""InstanceSearch.add_other_metrics：按补充指标查询 VM 并回填最大值。"""
from unittest.mock import patch

import pytest

from apps.monitor.models import Metric, MonitorObject
from apps.monitor.models.monitor_metrics import MetricGroup
from apps.monitor.services.monitor_instance import InstanceSearch

pytestmark = pytest.mark.django_db


def test_add_other_metrics_fills_max_value_from_vm():
    obj = MonitorObject.objects.create(
        name="Host-supp",
        supplementary_indicators=["uptime"],
        instance_id_keys=["instance"],
        default_metric="up",
    )
    group = MetricGroup.objects.create(name="g1", monitor_object=obj)
    Metric.objects.create(
        name="uptime",
        monitor_object=obj,
        metric_group=group,
        instance_id_keys=["instance"],
        query="uptime{__$labels__}",
        display_name="uptime",
        data_type="number",
        dimensions=[],
        description="",
        unit="",
    )
    search = InstanceSearch(obj, {})
    items = [{"instance_id": str(("h1",))}]
    vm = {
        "data": {
            "result": [
                {"metric": {"instance": "h1"}, "value": [0, "3"]},
                {"metric": {"instance": "h1"}, "value": [0, "9"]},
            ]
        }
    }
    with patch("apps.monitor.services.monitor_instance.VictoriaMetricsAPI") as api:
        api.return_value.query.return_value = vm
        search.add_other_metrics(items)
    assert items[0]["uptime"] == "9"
    sent = api.return_value.query.call_args.args[0]
    assert "instance=~" in sent
    assert "h1" in sent
