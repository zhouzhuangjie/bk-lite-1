"""日志聚类序列化器：训练数据按行解析、发布版本冲突与从文件创建。"""
import types
from unittest.mock import MagicMock

import pytest
from rest_framework import serializers

from apps.mlops.models.log_clustering import (
    LogClusteringDataset,
    LogClusteringDatasetRelease,
    LogClusteringTrainData,
)
from apps.mlops.serializers.log_clustering import (
    LogClusteringDatasetReleaseSerializer,
    LogClusteringTrainDataSerializer,
    LogClusteringTrainJobSerializer,
)
from .conftest import make_serializer_context

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


class _TextFile:
    def __init__(self, payload=b"line-a\n\nline-b\n"):
        self._payload = payload

    def __bool__(self):
        return True

    def read(self):
        return self._payload


def _ctx(monkeypatch, user, include=True):
    ctx = make_serializer_context(monkeypatch, user)
    ctx["request"] = types.SimpleNamespace(
        user=user,
        COOKIES={"current_team": "1"},
        query_params={
            "include_train_data": "true" if include else "false",
            "include_metadata": "true" if include else "false",
        },
    )
    return ctx


def test_train_data_to_representation_parses_lines_and_hides_when_disabled(monkeypatch, mlops_user):
    dataset = LogClusteringDataset.objects.create(name="lc-ds", description="", team=[1])
    instance = LogClusteringTrainData.objects.create(name="logs.txt", dataset=dataset, is_train_data=True)
    instance.train_data = _TextFile()
    instance.metadata = {"rows": 2}
    data = LogClusteringTrainDataSerializer(
        instance=instance, context=_ctx(monkeypatch, mlops_user)
    ).to_representation(instance)
    assert data["train_data"] == [{"log": "line-a"}, {"log": "line-b"}]
    assert data["metadata"] == {"rows": 2}

    hidden = LogClusteringTrainDataSerializer(
        instance=instance, context=_ctx(monkeypatch, mlops_user, include=False)
    ).to_representation(instance)
    assert "train_data" not in hidden
    assert "metadata" not in hidden


def test_train_data_to_representation_read_error_returns_empty(monkeypatch, mlops_user):
    dataset = LogClusteringDataset.objects.create(name="lc-ds2", description="", team=[1])
    instance = LogClusteringTrainData.objects.create(name="bad.txt", dataset=dataset, is_train_data=True)

    class Boom:
        def __bool__(self):
            return True

        def read(self):
            raise OSError("minio down")

    instance.train_data = Boom()
    data = LogClusteringTrainDataSerializer(
        instance=instance, context=_ctx(monkeypatch, mlops_user)
    ).to_representation(instance)
    assert data["train_data"] == []
    assert data["error"] == "读取训练数据失败: minio down"


def test_release_validate_rejects_duplicate_version_unless_failed_retry(monkeypatch, mlops_user):
    dataset = LogClusteringDataset.objects.create(name="lc-ds3", description="", team=[1])
    LogClusteringDatasetRelease.objects.create(dataset=dataset, version="v1", name="r1", status="published")
    ser = LogClusteringDatasetReleaseSerializer(context=make_serializer_context(monkeypatch, mlops_user))
    with pytest.raises(serializers.ValidationError) as exc:
        ser.validate({"dataset": dataset, "version": "v1"})
    assert str(exc.value.detail["version"]) == "数据集 lc-ds3 的版本 v1 已存在"

    failed = LogClusteringDatasetRelease.objects.create(dataset=dataset, version="v2", name="r2", status="failed")
    attrs = ser.validate({"dataset": dataset, "version": "v2", "train_file_id": 1, "val_file_id": 2, "test_file_id": 3})
    assert attrs["version"] == "v2"
    assert failed.status == "failed"


def test_create_from_files_retries_failed_and_marks_dispatch_error(monkeypatch, mlops_user):
    dataset = LogClusteringDataset.objects.create(name="lc-ds4", description="", team=[1])
    train = LogClusteringTrainData.objects.create(name="t", dataset=dataset, is_train_data=True)
    val = LogClusteringTrainData.objects.create(name="v", dataset=dataset, is_val_data=True)
    test = LogClusteringTrainData.objects.create(name="s", dataset=dataset, is_test_data=True)
    failed = LogClusteringDatasetRelease.objects.create(dataset=dataset, version="v3", name="old", status="failed")
    delay = MagicMock()
    monkeypatch.setattr("apps.mlops.tasks.log_clustering.publish_dataset_release_async.delay", delay)
    ser = LogClusteringDatasetReleaseSerializer(context=make_serializer_context(monkeypatch, mlops_user))
    release = ser._create_from_files({"dataset": dataset, "version": "v3"}, train.id, val.id, test.id)
    assert release.id == failed.id
    failed.refresh_from_db()
    assert failed.status == "pending"
    delay.assert_called_once_with(failed.id, train.id, val.id, test.id)

    delay.side_effect = RuntimeError("broker down")
    with pytest.raises(serializers.ValidationError, match="投递异步任务失败"):
        ser._create_from_files({"dataset": dataset, "version": "v4", "name": "n4"}, train.id, val.id, test.id)
    assert LogClusteringDatasetRelease.objects.get(dataset=dataset, version="v4").status == "failed"


def test_train_job_validate_requires_dataset_version(monkeypatch, mlops_user):
    ser = LogClusteringTrainJobSerializer(context=make_serializer_context(monkeypatch, mlops_user))
    with pytest.raises(serializers.ValidationError) as exc:
        ser.validate({})
    assert str(exc.value.detail["dataset_version"]) == "创建训练任务时必须指定数据集版本"
