"""训练数据 Serializer.to_representation：按 query 解析 CSV 或失败回空列表。"""
import io
import types

import pytest

from apps.mlops.models.anomaly_detection import AnomalyDetectionDataset, AnomalyDetectionTrainData
from apps.mlops.models.classification import ClassificationDataset, ClassificationTrainData
from apps.mlops.models.timeseries_predict import TimeSeriesPredictDataset, TimeSeriesPredictTrainData
from apps.mlops.serializers.anomaly_detection import AnomalyDetectionTrainDataSerializer
from apps.mlops.serializers.classification import ClassificationTrainDataSerializer
from apps.mlops.serializers.timeseries_predict import TimeSeriesPredictTrainDataSerializer
from .conftest import make_serializer_context

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


class _FakeFile:
    def __bool__(self):
        return True

    def open(self, mode="rb"):
        return io.BytesIO(b"timestamp,value,label\n2026-01-01 00:00:00,1.5,0\n")


def _context(monkeypatch, user, include=True):
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


def test_anomaly_to_representation_parses_csv_and_adds_index(monkeypatch, mlops_user):
    dataset = AnomalyDetectionDataset.objects.create(name="ad-ds", description="", team=[1])
    instance = AnomalyDetectionTrainData.objects.create(name="ad.csv", dataset=dataset, is_train_data=True)
    instance.train_data = _FakeFile()
    ser = AnomalyDetectionTrainDataSerializer(instance=instance, context=_context(monkeypatch, mlops_user))
    data = ser.to_representation(instance)
    assert isinstance(data["train_data"], list)
    assert data["train_data"][0]["index"] == 0
    assert data["train_data"][0]["value"] == 1.5
    assert isinstance(data["train_data"][0]["timestamp"], int)


def test_anomaly_to_representation_csv_error_returns_empty_list(monkeypatch, mlops_user):
    dataset = AnomalyDetectionDataset.objects.create(name="ad-ds2", description="", team=[1])
    instance = AnomalyDetectionTrainData.objects.create(name="bad.csv", dataset=dataset, is_train_data=True)

    class BoomFile:
        def __bool__(self):
            return True

        def open(self, mode="rb"):
            raise OSError("minio down")

    instance.train_data = BoomFile()
    ser = AnomalyDetectionTrainDataSerializer(instance=instance, context=_context(monkeypatch, mlops_user))
    data = ser.to_representation(instance)
    assert data["train_data"] == []


def test_timeseries_and_classification_to_representation_without_file(monkeypatch, mlops_user):
    ts_ds = TimeSeriesPredictDataset.objects.create(name="ts-ds", description="", team=[1])
    ts = TimeSeriesPredictTrainData.objects.create(name="ts.csv", dataset=ts_ds, is_train_data=True)
    ts_ser = TimeSeriesPredictTrainDataSerializer(
        instance=ts, context=_context(monkeypatch, mlops_user, include=False)
    )
    ts_data = ts_ser.to_representation(ts)
    assert "id" in ts_data
    assert ts_data["name"] == "ts.csv"

    clf_ds = ClassificationDataset.objects.create(name="clf-ds", description="", team=[1])
    clf = ClassificationTrainData.objects.create(name="clf.csv", dataset=clf_ds, is_train_data=True)
    clf_ser = ClassificationTrainDataSerializer(
        instance=clf, context=_context(monkeypatch, mlops_user, include=False)
    )
    clf_data = clf_ser.to_representation(clf)
    assert clf_data["name"] == "clf.csv"
