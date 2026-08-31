"""TeamModelViewSet：serving 容器清理失败阻断删除、数据集版本越权拒绝。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from rest_framework import serializers
from rest_framework.response import Response

from apps.mlops.utils.webhook_client import WebhookConnectionError, WebhookError, WebhookTimeoutError
from apps.mlops.views.anomaly_detection import AnomalyDetectionServingViewSet, AnomalyDetectionTrainJobViewSet

pytestmark = pytest.mark.unit


def test_cleanup_serving_runtime_success_not_found_and_errors():
    vs = AnomalyDetectionServingViewSet()
    serving = SimpleNamespace(id=9)

    with patch("apps.mlops.views.base.WebhookClient.remove") as remove:
        assert vs.cleanup_serving_runtime(serving) is None
    remove.assert_called_once_with("AnomalyDetection_Serving_9")

    with patch("apps.mlops.views.base.WebhookClient.remove", side_effect=WebhookError("container not found")):
        assert vs.cleanup_serving_runtime(serving) is None

    with patch("apps.mlops.views.base.WebhookClient.remove", side_effect=WebhookError("does not exist")):
        assert vs.cleanup_serving_runtime(serving) is None

    with patch("apps.mlops.views.base.WebhookClient.remove", side_effect=WebhookConnectionError("down")):
        resp = vs.cleanup_serving_runtime(serving)
    assert resp.status_code == 500
    assert "容器清理失败" in resp.data["error"]
    assert "down" in resp.data["error"]

    with patch("apps.mlops.views.base.WebhookClient.remove", side_effect=WebhookTimeoutError("slow")):
        timeout = vs.cleanup_serving_runtime(serving)
    assert timeout.status_code == 500
    assert "slow" in timeout.data["error"]

    with patch("apps.mlops.views.base.WebhookClient.remove", side_effect=WebhookError("permission denied")):
        blocked = vs.cleanup_serving_runtime(serving)
    assert blocked.status_code == 500
    assert "permission denied" in blocked.data["error"]


def test_destroy_train_job_stops_when_related_serving_cleanup_fails():
    vs = AnomalyDetectionTrainJobViewSet()
    first = SimpleNamespace(id=1)
    second = SimpleNamespace(id=2)
    vs.get_object = lambda: SimpleNamespace(id=10, servings=SimpleNamespace(all=lambda: [first, second]))
    err = Response({"error": "fail-1"}, status=500)
    vs.cleanup_serving_runtime = lambda serving: err if serving.id == 1 else None
    out = vs.destroy_train_job_with_runtime_cleanup(None)
    assert out is err


def test_destroy_serving_returns_cleanup_error_without_deleting():
    vs = AnomalyDetectionServingViewSet()
    vs.get_object = lambda: SimpleNamespace(id=4)
    err = Response({"error": "still-running"}, status=500)
    vs.cleanup_serving_runtime = lambda serving: err
    out = vs.destroy_serving_with_runtime_cleanup(None)
    assert out is err


def test_ensure_train_job_dataset_scope_ok_and_validation_error():
    vs = AnomalyDetectionTrainJobViewSet()
    request = SimpleNamespace()
    train_job = SimpleNamespace(dataset_version=3, team=[1])
    with patch("apps.mlops.views.base.assert_dataset_version_scope"):
        assert vs.ensure_train_job_dataset_scope(request, train_job) is None

    with patch(
        "apps.mlops.views.base.assert_dataset_version_scope",
        side_effect=serializers.ValidationError({"dataset_version": ["无权访问该数据集版本"]}),
    ):
        denied = vs.ensure_train_job_dataset_scope(request, train_job)
    assert denied.status_code == 400
    assert denied.data["error"] == "无权访问该数据集版本"

    with patch(
        "apps.mlops.views.base.assert_dataset_version_scope",
        side_effect=serializers.ValidationError("plain"),
    ):
        fallback = vs.ensure_train_job_dataset_scope(request, train_job)
    assert fallback.status_code == 400
    assert fallback.data["error"] == "训练任务关联的数据集版本无权访问"


def test_destroy_paths_call_super_after_successful_cleanup():
    from apps.core.utils.viewset_utils import AuthViewSet

    serving_vs = AnomalyDetectionServingViewSet()
    serving_vs.get_object = lambda: SimpleNamespace(id=4)
    serving_vs.cleanup_serving_runtime = lambda serving: None
    ok = Response(status=204)
    with patch.object(AuthViewSet, "destroy", return_value=ok) as destroy:
        assert serving_vs.destroy_serving_with_runtime_cleanup(None) is ok
    destroy.assert_called_once()

    train_vs = AnomalyDetectionTrainJobViewSet()
    train_vs.get_object = lambda: SimpleNamespace(
        id=10,
        servings=SimpleNamespace(all=lambda: [SimpleNamespace(id=1), SimpleNamespace(id=2)]),
    )
    cleaned = []
    train_vs.cleanup_serving_runtime = lambda serving: cleaned.append(serving.id)
    with patch.object(AuthViewSet, "destroy", return_value=ok) as destroy_job:
        assert train_vs.destroy_train_job_with_runtime_cleanup(None) is ok
    assert cleaned == [1, 2]
    destroy_job.assert_called_once()


def test_get_train_job_runs_none_without_experiment_then_fetches():
    vs = AnomalyDetectionTrainJobViewSet()
    job = SimpleNamespace(algorithm="iso", id=3)
    with (
        patch("apps.mlops.utils.mlflow_service.build_experiment_name", return_value="exp"),
        patch("apps.mlops.utils.mlflow_service.get_experiment_by_name", return_value=None),
    ):
        assert vs.get_train_job_runs(job) is None

    runs = object()
    with (
        patch("apps.mlops.utils.mlflow_service.build_experiment_name", return_value="exp"),
        patch(
            "apps.mlops.utils.mlflow_service.get_experiment_by_name",
            return_value=SimpleNamespace(experiment_id="e1"),
        ),
        patch("apps.mlops.utils.mlflow_service.get_experiment_runs", return_value=runs) as get_runs,
    ):
        assert vs.get_train_job_runs(job) is runs
    get_runs.assert_called_once_with("e1")
