"""采集任务 team 回填：空 ip_range 且空 team 才写入默认组织。"""
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command

from apps.cmdb.constants.constants import CollectPluginTypes
from apps.cmdb.models.collect_model import CollectModels

pytestmark = pytest.mark.django_db


def _task(name, ip_range, team):
    return CollectModels.objects.create(
        name=name,
        task_type=CollectPluginTypes.HOST,
        model_id="host",
        cycle_value_type="",
        ip_range=ip_range,
        team=team,
    )


def test_update_collect_task_data_fills_empty_team_only():
    empty_team = _task("t-empty", "", [])
    already = _task("t-keep", None, [8])
    skipped_range = _task("t-range", "10.0.0.0/24", [])
    with patch("apps.cmdb.management.commands.update_collect_task_data.get_default_group_id", return_value=1):
        out = StringIO()
        call_command("update_collect_task_data", stdout=out)
    empty_team.refresh_from_db()
    already.refresh_from_db()
    skipped_range.refresh_from_db()
    assert empty_team.team == 1
    assert already.team == [8]
    assert skipped_range.team == []


def test_update_collect_task_data_reraises_lookup_error():
    with (
        patch(
            "apps.cmdb.management.commands.update_collect_task_data.get_default_group_id",
            side_effect=RuntimeError("no default group"),
        ),
        pytest.raises(RuntimeError, match="no default group"),
    ):
        call_command("update_collect_task_data")
