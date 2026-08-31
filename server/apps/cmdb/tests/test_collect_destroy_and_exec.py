"""CollectModelService.destroy / exec_task：权限通过后清理周期任务并拒绝重复执行。"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.test import override_settings

from apps.cmdb.constants.constants import CollectPluginTypes, CollectRunStatusType
from apps.cmdb.models.collect_model import CollectModels
from apps.cmdb.services.collect_service import CollectModelService
from apps.core.exceptions.base_app_exception import BaseAppException

pytestmark = pytest.mark.django_db


def _task(**kwargs):
    defaults = dict(
        name="collect-destroy",
        task_type=CollectPluginTypes.HOST,
        model_id="host",
        cycle_value_type="cycle",
        is_interval=True,
        team=[1],
        exec_status=CollectRunStatusType.SUCCESS,
    )
    defaults.update(kwargs)
    return CollectModels.objects.create(**defaults)


def test_destroy_deletes_periodic_task_and_record(monkeypatch):
    instance = _task()
    view = MagicMock()
    view.get_object.return_value = instance
    view.delete_rules = MagicMock()
    request = SimpleNamespace(user=SimpleNamespace(username="op"))
    monkeypatch.setattr(CollectModelService, "has_permission", lambda *a, **k: None)
    monkeypatch.setattr(CollectModelService, "should_sync_node_params", lambda inst: True)
    delete_params = MagicMock()
    monkeypatch.setattr(CollectModelService, "delete_butch_node_params", delete_params)
    celery = MagicMock()
    monkeypatch.setattr("apps.cmdb.services.collect_service.CeleryUtils", celery)
    monkeypatch.setattr("apps.cmdb.services.collect_service.create_change_record", lambda **k: None)

    instance_id = instance.id
    deleted_id = CollectModelService.destroy(request, view)
    assert deleted_id == instance_id
    assert not CollectModels.objects.filter(id=instance_id).exists()
    celery.delete_periodic_task.assert_called_once_with(f"{CollectModelService.NAME}_{instance_id}")
    delete_params.assert_called_once()
    view.delete_rules.assert_called_once_with(instance_id, [1])


def test_destroy_rolls_back_when_external_cleanup_fails(monkeypatch):
    instance = _task(name="collect-destroy-fail")
    view = MagicMock()
    view.get_object.return_value = instance
    request = SimpleNamespace(user=SimpleNamespace(username="op"))
    monkeypatch.setattr(CollectModelService, "has_permission", lambda *a, **k: None)
    monkeypatch.setattr(CollectModelService, "should_sync_node_params", lambda inst: False)

    def boom(name):
        raise RuntimeError("celery down")

    monkeypatch.setattr("apps.cmdb.services.collect_service.CeleryUtils.delete_periodic_task", boom)
    with pytest.raises(BaseAppException, match="删除采集任务失败"):
        CollectModelService.destroy(request, view)
    assert CollectModels.objects.filter(id=instance.id).exists()


def test_exec_task_rejects_running_and_starts_idle(monkeypatch):
    running = _task(name="collect-running", exec_status=CollectRunStatusType.RUNNING)
    resp = CollectModelService.exec_task(running, "op")
    assert resp.status_code == 400

    idle = _task(name="collect-idle", exec_status=CollectRunStatusType.SUCCESS)
    monkeypatch.setattr(CollectModelService, "repair_host_cloud_snapshot", lambda inst: None)
    delayed = MagicMock()
    monkeypatch.setattr("apps.cmdb.services.collect_service.sync_collect_task", delayed)
    monkeypatch.setattr("apps.cmdb.services.collect_service.create_change_record", lambda **k: None)
    with override_settings(DEBUG=True):
        CollectModelService.exec_task(idle, "op")
    delayed.assert_called_once_with(idle.id)
    idle.refresh_from_db()
    assert idle.exec_status == CollectRunStatusType.RUNNING
    assert idle.format_data == {}
