"""policy_methods：剩余 step/归一化与全部 METHOD 对 VM 的入参契约。"""
from unittest.mock import patch

import pytest

from apps.core.exceptions.base_app_exception import BaseAppException
from apps.monitor.tasks.utils import policy_methods as pm

pytestmark = pytest.mark.unit


def test_period_step_day_and_invalid():
    assert pm.period_step("1d") == "48m"
    assert pm.period_step("2h") == "4m"
    assert pm.period_step("30h") == "1h"
    assert pm.period_step("1m") == "2s"
    with pytest.raises(BaseAppException, match="invalid period"):
        pm.period_step("")
    with pytest.raises(BaseAppException, match="invalid period"):
        pm.period_step("10x")


def test_normalize_policy_algorithms_rejects_invalid_group():
    with pytest.raises(BaseAppException, match="invalid group algorithm method"):
        pm.normalize_policy_algorithms("max_over_time", group_algorithm="median")
    with pytest.raises(BaseAppException, match="invalid algorithm method"):
        pm.normalize_policy_algorithms("median", group_algorithm="sum")
    assert pm.normalize_policy_algorithms("max_over_time", group_algorithm="max") == ("max", "max_over_time")


@pytest.mark.parametrize(
    "fn,query",
    [
        (pm._avg, "avg_over_time((avg(cpu) by (instance_id))[5m:10s])"),
        (pm._max, "max_over_time((max(cpu) by (instance_id))[5m:10s])"),
        (pm._min, "min_over_time((min(cpu) by (instance_id))[5m:10s])"),
        (pm._count, "last_over_time((count(cpu) by (instance_id))[5m:10s])"),
        (pm.min_over_time, "min_over_time((min(cpu) by (instance_id))[5m:10s])"),
        (pm.avg_over_time, "avg_over_time((avg(cpu) by (instance_id))[5m:10s])"),
        (pm.sum_over_time, "sum_over_time((sum(cpu) by (instance_id))[5m:10s])"),
        (pm.count_over_time, "count_over_time((count(cpu) by (instance_id))[5m:10s])"),
    ],
)
def test_remaining_methods_call_query_range(fn, query):
    with patch.object(pm, "VictoriaMetricsAPI") as mock_vm:
        inst = mock_vm.return_value
        inst.query_range.return_value = {"data": {"result": []}}
        assert fn("cpu", "s", "e", "5m", "instance_id") == {"data": {"result": []}}
    inst.query_range.assert_called_once_with(query, "s", "e", "5m")
