"""配置文件采集回调：payload 归一化与异常闭环。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.cmdb.models.config_file_version import ConfigFileVersionStatus
from apps.cmdb.services.config_file_service import ConfigFileService
from apps.core.exceptions.base_app_exception import BaseAppException

pytestmark = pytest.mark.unit


def test_normalize_collect_payload_flattens_nested_result():
    with pytest.raises(BaseAppException, match="配置文件采集回调格式错误"):
        ConfigFileService._normalize_collect_payload("x")
    payload = ConfigFileService._normalize_collect_payload(
        {
            "collect_result": {"status": "success", "file_path": "/etc/a.conf"},
            "config_file_name": "a.conf",
        }
    )
    assert payload["status"] == "success"
    assert payload["file_path"] == "/etc/a.conf"
    assert payload["file_name"] == "a.conf"
    assert ConfigFileService._normalize_version("1710000000") == "1710000000000"
    assert ConfigFileService._normalize_version("1710000000000") == "1710000000000"
    assert ConfigFileService._normalize_version("").isdigit()


def test_close_task_on_processing_error_ignores_stale_and_updates_known_instance():
    task = SimpleNamespace(id=1, params={"config_file_path": "/etc/a.conf"})
    with patch.object(ConfigFileService, "_is_stale_callback", return_value=True):
        assert ConfigFileService._close_task_on_processing_error(task, {"version": "1"}, RuntimeError("x")) is False

    with (
        patch.object(ConfigFileService, "_is_stale_callback", return_value=False),
        patch.object(ConfigFileService, "_get_expected_instance_ids", return_value=["h1"]),
        patch.object(ConfigFileService, "_resolve_task_instance", return_value=("h1", None)),
        patch.object(ConfigFileService, "_update_task_lifecycle", return_value=True) as update,
    ):
        assert (
            ConfigFileService._close_task_on_processing_error(task, {"instance_id": "h1", "version": "2"}, RuntimeError("boom"))
            is True
        )
    update.assert_called_once()
    assert update.call_args.kwargs["status"] == ConfigFileVersionStatus.ERROR
    assert update.call_args.kwargs["error_message"] == "boom"

    with (
        patch.object(ConfigFileService, "_is_stale_callback", return_value=False),
        patch.object(ConfigFileService, "_get_expected_instance_ids", return_value=[]),
        patch.object(ConfigFileService, "_resolve_task_instance", return_value=("", None)),
        patch.object(ConfigFileService, "_build_task_state", return_value={"items": {}}),
    ):
        assert ConfigFileService._close_task_on_processing_error(task, {"version": "3"}, RuntimeError("x")) is False
