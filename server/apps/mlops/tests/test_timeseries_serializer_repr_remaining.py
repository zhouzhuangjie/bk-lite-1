"""时间序列序列化器剩余：查询参数、CSV 解析与发布版本冲突。"""
import io
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from rest_framework import serializers

from apps.mlops.serializers.timeseries_predict import (
    TimeSeriesPredictDatasetReleaseSerializer,
    TimeSeriesPredictTrainDataSerializer,
    TimeSeriesPredictTrainJobSerializer,
)

pytestmark = pytest.mark.unit


def test_train_data_to_representation_parses_csv_and_hides_fields():
    ser = TimeSeriesPredictTrainDataSerializer.__new__(TimeSeriesPredictTrainDataSerializer)
    ser.include_train_data = True
    ser.include_metadata = True
    csv_bytes = b"timestamp,value\n2026-01-01 00:00:00,1.5\n"
    instance = SimpleNamespace(
        id=11,
        train_data=SimpleNamespace(open=lambda mode: io.BytesIO(csv_bytes)),
        metadata={"rows": 1},
    )
    with patch(
        "apps.mlops.serializers.timeseries_predict.AuthSerializer.to_representation",
        return_value={"id": 11, "train_data": "s3://x", "metadata": None},
    ):
        out = TimeSeriesPredictTrainDataSerializer.to_representation(ser, instance)
    assert out["train_data"][0]["value"] == 1.5
    assert out["train_data"][0]["index"] == 0
    assert isinstance(out["train_data"][0]["timestamp"], int)
    assert out["metadata"] == {"rows": 1}

    ser.include_train_data = False
    ser.include_metadata = False
    with patch(
        "apps.mlops.serializers.timeseries_predict.AuthSerializer.to_representation",
        return_value={"id": 11, "train_data": "s3://x", "metadata": {"rows": 1}},
    ):
        hidden = TimeSeriesPredictTrainDataSerializer.to_representation(ser, instance)
    assert "train_data" not in hidden
    assert "metadata" not in hidden


def test_train_data_to_representation_keeps_bad_timestamp_and_read_error():
    ser = TimeSeriesPredictTrainDataSerializer.__new__(TimeSeriesPredictTrainDataSerializer)
    ser.include_train_data = True
    ser.include_metadata = False
    instance = SimpleNamespace(
        id=12,
        train_data=SimpleNamespace(open=lambda mode: io.BytesIO(b"timestamp,value\nnot-a-date,2\n")),
        metadata=None,
    )
    with patch(
        "apps.mlops.serializers.timeseries_predict.AuthSerializer.to_representation",
        return_value={"id": 12, "train_data": "s3://x", "metadata": None},
    ):
        out = TimeSeriesPredictTrainDataSerializer.to_representation(ser, instance)
    assert out["train_data"][0]["timestamp"] == "not-a-date"

    instance.train_data = SimpleNamespace(open=lambda mode: (_ for _ in ()).throw(OSError("missing")))
    with patch(
        "apps.mlops.serializers.timeseries_predict.AuthSerializer.to_representation",
        return_value={"id": 12, "train_data": "s3://x", "metadata": None},
    ):
        failed = TimeSeriesPredictTrainDataSerializer.to_representation(ser, instance)
    assert failed["train_data"] == []
    assert failed["error"].startswith("读取训练数据失败:")


def test_train_job_requires_dataset_version_on_create():
    ser = TimeSeriesPredictTrainJobSerializer.__new__(TimeSeriesPredictTrainJobSerializer)
    ser.instance = None
    with pytest.raises(serializers.ValidationError) as exc:
        TimeSeriesPredictTrainJobSerializer.validate(ser, {})
    assert "dataset_version" in exc.value.detail


def test_dataset_release_validate_blocks_duplicate_and_allows_failed_retry():
    ser = TimeSeriesPredictDatasetReleaseSerializer.__new__(TimeSeriesPredictDatasetReleaseSerializer)
    ser.instance = None
    dataset = SimpleNamespace(name="ds1")
    existing = SimpleNamespace(status="ready", pk=1)
    qs = MagicMock()
    qs.exclude.return_value = qs
    qs.first.return_value = existing
    with patch(
        "apps.mlops.serializers.timeseries_predict.TimeSeriesPredictDatasetRelease.objects.filter",
        return_value=qs,
    ):
        with pytest.raises(serializers.ValidationError) as exc:
            TimeSeriesPredictDatasetReleaseSerializer.validate(
                ser, {"dataset": dataset, "version": "v1"}
            )
        assert "已存在" in str(exc.value.detail["version"])

        existing.status = "failed"
        out = TimeSeriesPredictDatasetReleaseSerializer.validate(
            ser,
            {"dataset": dataset, "version": "v1", "train_file_id": 1, "val_file_id": 2, "test_file_id": 3},
        )
        assert out["version"] == "v1"
