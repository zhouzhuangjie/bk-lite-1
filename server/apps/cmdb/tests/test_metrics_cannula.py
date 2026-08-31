"""MetricsCannula：指标拉取、新旧对比与采集控制器契约。

对照实现：default_metrics 存在时强制 manual=False；原始指标带 __time__；
filter_collect_task 决定是否按 collect_task 过滤图实体；manual 只走 update。
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.cmdb.collection.metrics_cannula import MetricsCannula
from apps.cmdb.constants.constants import DataCleanupStrategy

pytestmark = pytest.mark.unit


class _Plugin:
    def __init__(self, inst_name, inst_id, task_id, **kwargs):
        self.inst_name = inst_name
        self.inst_id = inst_id
        self.task_id = task_id
        self.kwargs = kwargs
        self.result = {"host": [{"inst_name": "h1"}]}
        self.raw_data = [
            {"metric": {"name": "cpu"}, "value": [1_700_000_000, "1"]},
            {"metric": {"name": "skip-ts"}, "value": [None, "0"]},
            {"no_metric": True},
        ]

    def run(self):
        return self.result


def test_init_with_default_metrics_forces_manual_false_and_skips_plugin():
    cannula = MetricsCannula(
        inst_id="i1",
        organization=[1],
        inst_name="host-a",
        task_id=9,
        collect_plugin=_Plugin,
        manual=True,
        default_metrics={"host": [{"inst_name": "preset"}]},
        plugin_kwargs={"region": "cn"},
    )
    assert cannula.manual is False
    assert cannula.task_id == "9"
    assert cannula.data_cleanup_strategy == DataCleanupStrategy.NO_CLEANUP
    assert cannula.collection_metrics == {"host": [{"inst_name": "preset"}]}
    assert cannula.raw_data == []


def test_get_collection_metrics_stamps_vm_time_and_skips_empty():
    cannula = MetricsCannula(
        inst_id="i2",
        organization=[2],
        inst_name="host-b",
        task_id=3,
        collect_plugin=_Plugin,
        plugin_kwargs={"zone": "a"},
    )
    assert cannula.collection_metrics == {"host": [{"inst_name": "h1"}]}
    assert cannula.raw_data[0]["name"] == "cpu"
    assert cannula.raw_data[0]["__time__"].endswith("+00:00")
    assert cannula.raw_data[1] == {"name": "skip-ts"}
    assert len(cannula.raw_data) == 2


def test_contrast_classifies_add_update_delete():
    old_map = {"keep": {"_id": 1, "name": "old"}, "gone": {"_id": 2, "name": "gone"}}
    new_map = {"keep": {"name": "new"}, "fresh": {"name": "fresh"}}
    add_list, update_list, delete_list = MetricsCannula.contrast(old_map, new_map)
    assert add_list == [{"name": "fresh"}]
    assert update_list == [{"name": "new", "_id": 1}]
    assert delete_list == [{"_id": 2, "name": "gone"}]


def test_collect_controller_filters_task_and_uses_update_when_manual():
    cannula = MetricsCannula(
        inst_id="i3",
        organization=[7],
        inst_name="host-c",
        task_id=5,
        collect_plugin=_Plugin,
        default_metrics={"host": [{"inst_name": "h1"}], "disk": [{"inst_name": "d1"}]},
        filter_collect_task=True,
    )
    # default_metrics 会关掉 manual，这里单独打开以覆盖 update 分支
    cannula.manual = True
    cannula.raw_data = [{"name": "cpu"}]

    graph = MagicMock()
    graph.__enter__.return_value = graph
    graph.__exit__.return_value = False
    graph.query_entity.return_value = ([{"inst_name": "old"}], None)

    management = SimpleNamespace(
        add_list=[{"inst_name": "h1"}],
        delete_list=[{"inst_name": "old"}],
        update=MagicMock(return_value={"updated": 1}),
        controller=MagicMock(return_value={"created": 1}),
    )

    with (
        patch("apps.cmdb.collection.metrics_cannula.GraphClient", return_value=graph),
        patch("apps.cmdb.collection.metrics_cannula.Management", return_value=management) as mgmt,
    ):
        result = cannula.collect_controller()

    assert result["host"] == {"updated": 1}
    assert result["disk"] == {"updated": 1}
    assert result["__raw_data__"] == [{"name": "cpu"}]
    assert result["all"] == 2
    assert cannula.add_list == [{"inst_name": "h1"}, {"inst_name": "h1"}]
    assert cannula.delete_list == [{"inst_name": "old"}, {"inst_name": "old"}]
    management.update.assert_called()
    management.controller.assert_not_called()
    first_params = graph.query_entity.call_args_list[0].args[1]
    assert first_params == [
        {"field": "model_id", "type": "str=", "value": "host"},
        {"field": "collect_task", "type": "str=", "value": "5"},
    ]
    assert mgmt.call_args.kwargs["data_cleanup_strategy"] == DataCleanupStrategy.NO_CLEANUP


def test_collect_controller_skips_task_filter_and_runs_controller():
    cannula = MetricsCannula(
        inst_id="i4",
        organization=[1],
        inst_name="host-d",
        task_id=8,
        collect_plugin=_Plugin,
        default_metrics={"host": [{"inst_name": "h1"}]},
        filter_collect_task=False,
        data_cleanup_strategy=DataCleanupStrategy.IMMEDIATELY,
    )
    graph = MagicMock()
    graph.__enter__.return_value = graph
    graph.__exit__.return_value = False
    graph.query_entity.return_value = ([], None)
    management = SimpleNamespace(
        add_list=[],
        delete_list=[],
        update=MagicMock(),
        controller=MagicMock(return_value={"created": 2}),
    )
    with (
        patch("apps.cmdb.collection.metrics_cannula.GraphClient", return_value=graph),
        patch("apps.cmdb.collection.metrics_cannula.Management", return_value=management),
    ):
        result = cannula.collect_controller()
    assert result["host"] == {"created": 2}
    assert result["all"] == 1
    management.controller.assert_called_once()
    management.update.assert_not_called()
    assert graph.query_entity.call_args.args[1] == [{"field": "model_id", "type": "str=", "value": "host"}]
