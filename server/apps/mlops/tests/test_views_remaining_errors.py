"""六套算法视图剩余错误分支：run 指标/删除 500、serving remove 超时/连接失败。"""
import types
from unittest.mock import Mock

import pydantic.root_model  # noqa
import pytest
from rest_framework import status
from rest_framework.test import APIRequestFactory

from apps.base.tests.factories import UserFactory
from apps.mlops.constants import TrainJobStatus
from apps.mlops.utils.webhook_client import WebhookConnectionError, WebhookError, WebhookTimeoutError

from apps.mlops.tests.test_views_actions_param import (
    ALGOS,
    ALGO_IDS,
    _call,
    _make_serving,
    _make_train_job,
    _patch_mlflow,
    _runs_frame,
    _view_module,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

factory = APIRequestFactory()


@pytest.fixture
def superuser():
    return UserFactory(username="mlops-err-su", domain="domain.com", roles=[], is_superuser=True)


@pytest.mark.parametrize("suffix,prefix,model_module,basename", ALGOS, ids=ALGO_IDS)
def test_metrics_list_generic_exception_returns_500(monkeypatch, superuser, suffix, prefix, model_module, basename):
    tj = _make_train_job(model_module, basename)
    mod = _view_module(suffix)
    _patch_mlflow(
        monkeypatch,
        suffix,
        get_experiment_by_name=lambda name: types.SimpleNamespace(experiment_id="1"),
        get_experiment_runs=lambda eid, **kw: _runs_frame([{"run_id": "run-1"}]),
        get_run_metrics=Mock(side_effect=RuntimeError("mlflow down")),
    )
    vs = getattr(mod, f"{basename}TrainJobViewSet")
    view = vs.as_view({"get": "get_runs_metrics_list"})
    request = factory.get(f"/{suffix}_train_jobs/x/runs/run-1/metrics_list/")
    resp = _call(view, request, superuser, pk=tj.id, run_id="run-1")
    assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert "获取指标列表失败" in resp.data["error"]


@pytest.mark.parametrize("suffix,prefix,model_module,basename", ALGOS, ids=ALGO_IDS)
def test_delete_run_generic_exception_returns_500(monkeypatch, superuser, suffix, prefix, model_module, basename):
    tj = _make_train_job(model_module, basename, status_value=TrainJobStatus.COMPLETED)
    mod = _view_module(suffix)
    _patch_mlflow(
        monkeypatch,
        suffix,
        get_experiment_by_name=lambda name: types.SimpleNamespace(experiment_id="1"),
        get_experiment_runs=lambda eid, **kw: _runs_frame([{"run_id": "run-1", "status": "FINISHED"}]),
        delete_run=Mock(side_effect=RuntimeError("cannot delete")),
    )
    vs = getattr(mod, f"{basename}TrainJobViewSet")
    view = vs.as_view({"delete": "delete_run"})
    request = factory.delete(f"/{suffix}_train_jobs/x/runs/run-1/")
    resp = _call(view, request, superuser, pk=tj.id, run_id="run-1")
    assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert "删除 run 失败" in resp.data["message"]


@pytest.mark.parametrize("suffix,prefix,model_module,basename", ALGOS, ids=ALGO_IDS)
def test_serving_remove_timeout_and_connection_errors(monkeypatch, superuser, suffix, prefix, model_module, basename):
    serving = _make_serving(model_module, basename, container_info={"state": "running"})
    mod = _view_module(suffix)
    vs = getattr(mod, f"{basename}ServingViewSet")
    if not hasattr(vs, "remove"):
        pytest.skip(f"{suffix} serving has no remove action")
    view = vs.as_view({"post": "remove"})

    monkeypatch.setattr(mod.WebhookClient, "remove", staticmethod(Mock(side_effect=WebhookTimeoutError("timed out"))))
    resp = _call(view, factory.post(f"/{suffix}_servings/x/remove/"), superuser, pk=serving.id)
    assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert resp.data["error"] == "timed out"

    monkeypatch.setattr(
        mod.WebhookClient,
        "remove",
        staticmethod(Mock(side_effect=WebhookConnectionError("conn refused"))),
    )
    resp = _call(view, factory.post(f"/{suffix}_servings/x/remove/"), superuser, pk=serving.id)
    assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert resp.data["error"] == "conn refused"

    monkeypatch.setattr(mod.WebhookClient, "remove", staticmethod(Mock(side_effect=WebhookError("other", code="X"))))
    resp = _call(view, factory.post(f"/{suffix}_servings/x/remove/"), superuser, pk=serving.id)
    assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert resp.data["error"] == "other"
