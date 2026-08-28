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
    team_a = 881001
    team_b = 881002
    CollectModels.objects.create(
        name="stat-ok-881001",
        task_type=CollectPluginTypes.HOST,
        model_id="host-stat-881001",
        cycle_value_type="cycle",
        team=[team_a],
        is_interval=True,
        exec_status=CollectRunStatusType.SUCCESS,
    )
    CollectModels.objects.create(
        name="stat-err-881001",
        task_type=CollectPluginTypes.HOST,
        model_id="host-stat-881001-err",
        cycle_value_type="cycle",
        team=[team_a],
        is_interval=False,
        exec_status=CollectRunStatusType.ERROR,
    )
    CollectModels.objects.create(
        name="stat-other-881002",
        task_type=CollectPluginTypes.HOST,
        model_id="host-stat-881002",
        cycle_value_type="cycle",
        team=[team_b],
        exec_status=CollectRunStatusType.SUCCESS,
    )
    data = N.get_cmdb_collect_statistics(user_info={"team": team_a})["data"]
    assert data["task_count"] == 2
    assert data["interval_task_count"] == 1
    assert data["success_count"] == 1
    assert data["error_count"] == 1
    other = N.get_cmdb_collect_statistics(user_info={"team": team_b})["data"]
    assert other["task_count"] == 1
    assert other["success_count"] == 1
    assert other["error_count"] == 0
