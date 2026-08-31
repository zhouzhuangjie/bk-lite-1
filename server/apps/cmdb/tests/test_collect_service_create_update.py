"""CollectModelService.create / update：周期任务、节点参数与外部失败回滚。"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.cmdb.constants.constants import CollectPluginTypes
from apps.cmdb.models.collect_model import CollectModels
from apps.cmdb.services.collect_service import CollectModelService
from apps.core.exceptions.base_app_exception import BaseAppException

pytestmark = pytest.mark.django_db


def _task(**kwargs):
    defaults = dict(
        name="collect-upd",
        task_type=CollectPluginTypes.HOST,
        model_id="host",
        cycle_value_type="cycle",
        is_interval=False,
        team=[1],
    )
    defaults.update(kwargs)
    return CollectModels.objects.create(**defaults)


def _view(instance, perform=None):
    serializer = MagicMock()
    serializer.instance = instance
    serializer.is_valid.return_value = True
    view = MagicMock()
    view.get_object.return_value = instance
    view.get_serializer.return_value = serializer
    if perform:
        view.perform_update.side_effect = perform
        view.perform_create.side_effect = perform
    return view, serializer


def test_update_without_interval_deletes_periodic_task_and_syncs_nodes(monkeypatch):
    instance = _task(name="old-name")
    view, _ = _view(instance)

    monkeypatch.setattr(
        CollectModelService,
        "format_params",
        lambda data: ({"name": "new-name", "team": [1]}, False, None),
    )
    monkeypatch.setattr(CollectModelService, "has_permission", lambda *a, **k: None)
    monkeypatch.setattr(CollectModelService, "format_update_credential", lambda *a, **k: None)
    monkeypatch.setattr(CollectModelService, "enrich_host_cloud_snapshot_payload", lambda *a, **k: None)
    monkeypatch.setattr(CollectModelService, "should_sync_node_params", lambda inst: True)
    delete_params = MagicMock()
    push_params = MagicMock()
    delete_team = MagicMock()
    monkeypatch.setattr(CollectModelService, "delete_butch_node_params", delete_params)
    monkeypatch.setattr(CollectModelService, "push_butch_node_params", push_params)
    monkeypatch.setattr(CollectModelService, "delete_team", delete_team)
    celery = MagicMock()
    monkeypatch.setattr("apps.cmdb.services.collect_service.CeleryUtils", celery)
    change = MagicMock()
    monkeypatch.setattr("apps.cmdb.services.collect_service.create_change_record", change)

    request = SimpleNamespace(user=SimpleNamespace(username="alice"), data={"team": [1]})
    result_id = CollectModelService.update(request, view)

    assert result_id == instance.id
    celery.delete_periodic_task.assert_called_once_with(f"{CollectModelService.NAME}_{instance.id}")
    celery.create_or_update_periodic_task.assert_not_called()
    delete_params.assert_called_once()
    push_params.assert_called_once()
    delete_team.assert_called_once()
    change.assert_called_once()
    assert change.call_args.kwargs["operator"] == "alice"


def test_update_external_failure_raises_and_does_not_write_change(monkeypatch):
    instance = _task()
    view, _ = _view(instance)
    monkeypatch.setattr(
        CollectModelService,
        "format_params",
        lambda data: ({"name": "x", "team": [1]}, True, "*/5 * * * *"),
    )
    monkeypatch.setattr(CollectModelService, "has_permission", lambda *a, **k: None)
    monkeypatch.setattr(CollectModelService, "format_update_credential", lambda *a, **k: None)
    monkeypatch.setattr(CollectModelService, "enrich_host_cloud_snapshot_payload", lambda *a, **k: None)
    monkeypatch.setattr(CollectModelService, "should_sync_node_params", lambda inst: True)
    monkeypatch.setattr(
        CollectModelService,
        "delete_butch_node_params",
        MagicMock(side_effect=RuntimeError("rpc down")),
    )
    celery = MagicMock()
    monkeypatch.setattr("apps.cmdb.services.collect_service.CeleryUtils", celery)
    change = MagicMock()
    monkeypatch.setattr("apps.cmdb.services.collect_service.create_change_record", change)

    request = SimpleNamespace(user=SimpleNamespace(username="alice"), data={"team": [1]})
    with pytest.raises(BaseAppException, match="更新采集任务失败"):
        CollectModelService.update(request, view)
    change.assert_not_called()


def test_create_interval_registers_periodic_task_and_pushes_nodes(monkeypatch):
    created = {"inst": None}

    def perform_create(serializer):
        created["inst"] = _task(name="created-task", is_interval=True)
        serializer.instance = created["inst"]

    view, serializer = _view(None, perform=perform_create)
    monkeypatch.setattr(
        CollectModelService,
        "format_params",
        lambda data: ({"name": "created-task", "team": [1]}, True, "0 * * * *"),
    )
    monkeypatch.setattr(CollectModelService, "enrich_host_cloud_snapshot_payload", lambda *a, **k: None)
    monkeypatch.setattr(CollectModelService, "should_sync_node_params", lambda inst: True)
    push = MagicMock()
    monkeypatch.setattr(CollectModelService, "push_butch_node_params", push)
    delayed = MagicMock()
    monkeypatch.setattr(CollectModelService, "schedule_delayed_sync_if_needed", delayed)
    celery = MagicMock()
    monkeypatch.setattr("apps.cmdb.services.collect_service.CeleryUtils", celery)
    change = MagicMock()
    monkeypatch.setattr("apps.cmdb.services.collect_service.create_change_record", change)

    request = SimpleNamespace(user=SimpleNamespace(username="bob"), data={"team": [1]})
    result_id = CollectModelService.create(request, view)

    assert result_id == created["inst"].id
    celery.create_or_update_periodic_task.assert_called_once()
    push.assert_called_once_with(created["inst"])
    delayed.assert_called_once()
    change.assert_called_once()
    assert change.call_args.kwargs["operator"] == "bob"
