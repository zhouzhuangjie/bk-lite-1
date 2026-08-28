"""policy_methods 测试 — 两段聚合查询构建 + 聚合方法对 VM 边界的入参契约。"""
from unittest.mock import patch

import pytest

from apps.core.exceptions.base_app_exception import BaseAppException
from apps.monitor.tasks.utils import policy_methods as pm

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("period,expected", [
    ({"type": "min", "value": 5}, 300),
    ({"type": "hour", "value": 2}, 7200),
    ({"type": "day", "value": 1}, 86400),
])
def test_period_to_seconds(period, expected):
    assert pm.period_to_seconds(period) == expected


def test_period_to_seconds_empty_raises():
    with pytest.raises(BaseAppException, match="period is empty"):
        pm.period_to_seconds(None)


def test_period_to_seconds_invalid_type_raises():
    with pytest.raises(BaseAppException, match="invalid period type"):
        pm.period_to_seconds({"type": "week", "value": 1})


def test_period_step_uses_thirty_buckets():
    assert pm.period_step("5m") == "10s"
    assert pm.period_step("30m") == "1m"
    assert pm.period_step("1h") == "2m"


def test_build_policy_query_legacy_sum_expands_to_two_stage():
    assert pm.build_policy_query("sum", "cpu", "5m", "instance_id") == (
        "sum_over_time((sum(cpu) by (instance_id))[5m:10s])"
    )


def test_build_policy_query_explicit_window_and_group_algorithm():
    q = pm.build_policy_query("max_over_time", "cpu", "5m", "instance_id", group_algorithm="max")
    assert q == "max_over_time((max(cpu) by (instance_id))[5m:10s])"


def test_build_policy_query_complex_metric_stays_inside_group_stage():
    q = pm.build_policy_query("avg_over_time", "rate(cpu[1m])", "5m", "instance_id", group_algorithm="avg")
    assert q == "avg_over_time((avg(rate(cpu[1m])) by (instance_id))[5m:10s])"


def test_build_policy_query_invalid_algorithm_raises():
    with pytest.raises(BaseAppException, match="invalid algorithm method"):
        pm.build_policy_query("median", "cpu", "5m", "instance_id")


def test_build_policy_query_requires_group_by():
    with pytest.raises(BaseAppException, match="group_by is required"):
        pm.build_policy_query("sum", "cpu", "5m", "")


def test_sum_calls_vm_query_range_with_two_stage_query():
    with patch.object(pm, "VictoriaMetricsAPI") as MockVM:
        inst = MockVM.return_value
        inst.query_range.return_value = {"data": {"result": []}}
        out = pm._sum("cpu", "s", "e", "5m", "instance_id")
    inst.query_range.assert_called_once_with(
        "sum_over_time((sum(cpu) by (instance_id))[5m:10s])", "s", "e", "5m"
    )
    assert out == {"data": {"result": []}}


def test_max_over_time_calls_query_range():
    with patch.object(pm, "VictoriaMetricsAPI") as MockVM:
        inst = MockVM.return_value
        inst.query_range.return_value = {"data": {"result": []}}
        pm.max_over_time("cpu", "s", "e", "5m", "instance_id")
    inst.query_range.assert_called_once_with(
        "max_over_time((max(cpu) by (instance_id))[5m:10s])", "s", "e", "5m"
    )


def test_last_over_time_uses_query_range():
    with patch.object(pm, "VictoriaMetricsAPI") as MockVM:
        inst = MockVM.return_value
        inst.query_range.return_value = {"data": {"result": [{"value": [123, "9"]}]}}
        out = pm.last_over_time("cpu", "s", "e", "5m", "instance_id")
    inst.query_range.assert_called_once_with(
        "last_over_time((avg(cpu) by (instance_id))[5m:10s])", "s", "e", "5m"
    )
    assert out["data"]["result"][0]["value"] == [123, "9"]


def test_method_registry_maps_all_algorithms():
    assert set(pm.METHOD) == {
        "sum", "avg", "max", "min", "count",
        "max_over_time", "min_over_time", "avg_over_time", "sum_over_time", "count_over_time", "last_over_time",
    }
