"""CMDB 采集健康 NATS：无组织全 0；按团队统计 interval/成功数。"""
import pytest

from apps.cmdb.constants.constants import CollectPluginTypes, CollectRunStatusType
from apps.cmdb.models.collect_model import CollectModels
from apps.cmdb.nats import nats as N

pytestmark = pytest.mark.django_db


def test_collect_statistics_empty_without_team():
    result = N.get_cmdb_collect_statistics(user_info=None)
    assert result["result"] is True
    data = result["data"]
    assert data["task_count"] == 0
    assert data["interval_task_count"] == 0
    assert data["success_count"] == 0


def test_collect_statistics_counts_team_tasks():
    CollectModels.objects.create(
        name="stat-ok",
        task_type=CollectPluginTypes.HOST,
        model_id="host",
        cycle_value_type="cycle",
        team=[1],
        is_interval=True,
        exec_status=CollectRunStatusType.SUCCESS,
    )
    CollectModels.objects.create(
        name="stat-err",
        task_type=CollectPluginTypes.HOST,
        model_id="host",
        cycle_value_type="cycle",
        team=[1],
        is_interval=False,
        exec_status=CollectRunStatusType.ERROR,
    )
    CollectModels.objects.create(
        name="stat-other",
        task_type=CollectPluginTypes.HOST,
        model_id="host",
        cycle_value_type="cycle",
        team=[99],
        exec_status=CollectRunStatusType.SUCCESS,
    )
    result = N.get_cmdb_collect_statistics(user_info={"team": 1})
    data = result["data"]
    assert data["task_count"] >= 2
    assert data["interval_task_count"] >= 1
    assert data["success_count"] >= 1
    assert data["error_count"] >= 1
