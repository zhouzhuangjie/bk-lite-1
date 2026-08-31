"""poll_train_job_status 剩余：实验缺失、run 竞态、状态映射、未知 prefix。"""
from types import SimpleNamespace

import pandas as pd
import pytest
from celery.exceptions import Retry, SoftTimeLimitExceeded

from apps.mlops.constants import TrainJobStatus
from apps.mlops.models.classification import ClassificationTrainJob
from apps.mlops.tasks.poll_train_job_status import (
    _get_train_job_model,
    _load_train_job,
    _mark_train_job_failed,
    poll_train_job_status,
)
from apps.mlops.utils.webhook_client import WebhookError

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _job(**kwargs):
    defaults = dict(
        name="poll-remaining",
        description="",
        team=[1],
        status=TrainJobStatus.RUNNING,
        algorithm="demo-algorithm",
        dataset_version=None,
        hyperopt_config={},
    )
    defaults.update(kwargs)
    defaults["name"] = kwargs.get("name", defaults["name"] + "-" + str(ClassificationTrainJob.objects.count()))
    return ClassificationTrainJob.objects.create(**defaults)


def _retry_raises(*args, **kwargs):
    raise Retry()


def test_unknown_prefix_and_missing_or_idle_job_skip_polling():
    assert _get_train_job_model("NoSuchAlgo") is None
    assert _load_train_job(1, "NoSuchAlgo") is None
    assert poll_train_job_status.run(1, "NoSuchAlgo") == {
        "result": False,
        "reason": "train_job not found or not running",
    }
    assert _load_train_job(999999, "Classification") is None
    idle = _job(status=TrainJobStatus.COMPLETED, name="idle")
    assert _load_train_job(idle.id, "Classification") is None
    _mark_train_job_failed(1, "NoSuchAlgo")
    running = _job(name="mark-ok")
    _mark_train_job_failed(running.id, "Classification")
    running.refresh_from_db()
    assert running.status == TrainJobStatus.FAILED

    class Boom:
        DoesNotExist = ClassificationTrainJob.DoesNotExist

        class objects:
            @staticmethod
            def filter(**kwargs):
                raise RuntimeError("db down")

    monkey_job = _job(name="mark-err")
    orig = _mark_train_job_failed.__globals__["_get_train_job_model"]
    try:
        _mark_train_job_failed.__globals__["_get_train_job_model"] = lambda prefix: Boom
        _mark_train_job_failed(monkey_job.id, "Classification")
    finally:
        _mark_train_job_failed.__globals__["_get_train_job_model"] = orig
    monkey_job.refresh_from_db()
    assert monkey_job.status == TrainJobStatus.RUNNING


def test_missing_experiment_empty_runs_and_run_count_retry(monkeypatch):
    job = _job(name="wait-exp")
    monkeypatch.setattr(poll_train_job_status, "retry", _retry_raises)
    monkeypatch.setattr("apps.mlops.utils.mlflow_service.get_experiment_by_name", lambda name: None)
    with pytest.raises(Retry):
        poll_train_job_status.run(job.id, "Classification")

    monkeypatch.setattr(
        "apps.mlops.utils.mlflow_service.get_experiment_by_name",
        lambda name: SimpleNamespace(experiment_id="e1"),
    )
    monkeypatch.setattr("apps.mlops.utils.mlflow_service.get_experiment_runs", lambda eid: pd.DataFrame())
    with pytest.raises(Retry):
        poll_train_job_status.run(job.id, "Classification")

    monkeypatch.setattr(
        "apps.mlops.utils.mlflow_service.get_experiment_runs",
        lambda eid: pd.DataFrame([{"status": "RUNNING"}]),
    )
    with pytest.raises(Retry):
        poll_train_job_status.run(job.id, "Classification", expected_run_count=2)
    with pytest.raises(Retry):
        poll_train_job_status.run(job.id, "Classification", expected_run_count=0)


def test_finished_failed_and_unknown_mlflow_status_map(monkeypatch):
    finished = _job(name="fin")
    monkeypatch.setattr(
        "apps.mlops.utils.mlflow_service.get_experiment_by_name",
        lambda name: SimpleNamespace(experiment_id="e1"),
    )
    monkeypatch.setattr(
        "apps.mlops.utils.mlflow_service.get_experiment_runs",
        lambda eid: pd.DataFrame([{"status": "FINISHED"}]),
    )
    out = poll_train_job_status.run(finished.id, "Classification")
    assert out == {"result": True, "train_job_id": finished.id, "final_status": TrainJobStatus.COMPLETED}
    finished.refresh_from_db()
    assert finished.status == TrainJobStatus.COMPLETED

    unknown = _job(name="unk")
    monkeypatch.setattr(
        "apps.mlops.utils.mlflow_service.get_experiment_runs",
        lambda eid: pd.DataFrame([{"status": "WEIRD"}]),
    )
    out = poll_train_job_status.run(unknown.id, "Classification")
    assert out["final_status"] == TrainJobStatus.FAILED
    unknown.refresh_from_db()
    assert unknown.status == TrainJobStatus.FAILED

    skipped = _job(name="skipped")
    monkeypatch.setattr(
        "apps.mlops.utils.mlflow_service.get_experiment_runs",
        lambda eid: pd.DataFrame([{"status": "FINISHED"}]),
    )
    ClassificationTrainJob.objects.filter(id=skipped.id).update(status=TrainJobStatus.FAILED)
    out = poll_train_job_status.run(skipped.id, "Classification")
    assert out["reason"] == "train_job not found or not running"


def test_retry_is_reraised_and_soft_limit_retries_before_fuse(monkeypatch):
    job = _job(name="retry-prop")
    monkeypatch.setattr(
        "apps.mlops.utils.mlflow_service.get_experiment_by_name",
        lambda name: (_ for _ in ()).throw(Retry()),
    )
    with pytest.raises(Retry):
        poll_train_job_status.run(job.id, "Classification")

    retry_calls = []

    def fake_retry(*args, **kwargs):
        retry_calls.append(kwargs)
        raise Retry()

    monkeypatch.setattr(poll_train_job_status, "retry", fake_retry)
    monkeypatch.setattr(
        "apps.mlops.utils.mlflow_service.get_experiment_by_name",
        lambda name: (_ for _ in ()).throw(SoftTimeLimitExceeded()),
    )
    with pytest.raises(Retry):
        poll_train_job_status.run(job.id, "Classification", consecutive_errors=0)
    assert retry_calls[0]["kwargs"]["consecutive_errors"] == 1


def test_observation_marks_failed_when_container_stopped(monkeypatch):
    job = _job(name="stopped")
    monkeypatch.setattr(
        "apps.mlops.utils.mlflow_service.get_experiment_by_name",
        lambda name: (_ for _ in ()).throw(RuntimeError("mlflow down")),
    )
    monkeypatch.setattr(
        "apps.mlops.utils.webhook_client.WebhookClient.get_status",
        lambda ids: [{"id": ids[0], "status": "success", "state": "exited"}],
    )
    out = poll_train_job_status.run(job.id, "Classification", consecutive_errors=9)
    assert out == {"result": False, "reason": "container not running after observation failures"}
    job.refresh_from_db()
    assert job.status == TrainJobStatus.FAILED


def test_observation_webhook_error_retries_before_max(monkeypatch):
    job = _job(name="wh-err")
    retry_calls = []

    def fake_retry(*args, **kwargs):
        retry_calls.append(kwargs)
        raise Retry()

    monkeypatch.setattr(poll_train_job_status, "retry", fake_retry)
    monkeypatch.setattr(
        "apps.mlops.utils.mlflow_service.get_experiment_by_name",
        lambda name: (_ for _ in ()).throw(RuntimeError("mlflow down")),
    )
    monkeypatch.setattr(
        "apps.mlops.utils.webhook_client.WebhookClient.get_status",
        lambda ids: (_ for _ in ()).throw(WebhookError("down")),
    )
    with pytest.raises(Retry):
        poll_train_job_status.run(job.id, "Classification", consecutive_errors=9)
    assert retry_calls[0]["countdown"] == 300
    job.refresh_from_db()
    assert job.status == TrainJobStatus.RUNNING
