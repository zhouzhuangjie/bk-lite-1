"""图片分类序列化器剩余：查询参数、版本格式、超参与服务端口。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from rest_framework import serializers

from apps.mlops.serializers.image_classification import (
    ImageClassificationDatasetReleaseSerializer,
    ImageClassificationServingSerializer,
    ImageClassificationTrainDataSerializer,
    ImageClassificationTrainJobSerializer,
)

pytestmark = pytest.mark.unit


def test_train_data_include_flags_and_to_representation():
    ser = ImageClassificationTrainDataSerializer.__new__(ImageClassificationTrainDataSerializer)
    ser.include_train_data = False
    ser.include_metadata = False
    with patch(
        "apps.mlops.serializers.image_classification.AuthSerializer.to_representation",
        return_value={"train_data": "blob", "metadata": {"n": 1}},
    ):
        hidden = ImageClassificationTrainDataSerializer.to_representation(ser, SimpleNamespace())
    assert "train_data" not in hidden
    assert "metadata" not in hidden
    ser.include_train_data = True
    ser.include_metadata = True
    with patch(
        "apps.mlops.serializers.image_classification.AuthSerializer.to_representation",
        return_value={"train_data": "blob", "metadata": {"n": 1}},
    ):
        shown = ImageClassificationTrainDataSerializer.to_representation(ser, SimpleNamespace())
    assert shown["train_data"] == "blob"
    assert shown["metadata"] == {"n": 1}


def test_dataset_release_version_and_file_requirement():
    ser = ImageClassificationDatasetReleaseSerializer.__new__(ImageClassificationDatasetReleaseSerializer)
    ser.instance = None
    assert ImageClassificationDatasetReleaseSerializer.validate_version(ser, "v1.0.0") == "v1.0.0"
    with pytest.raises(serializers.ValidationError, match="版本号格式应为"):
        ImageClassificationDatasetReleaseSerializer.validate_version(ser, "1.0")
    with pytest.raises(serializers.ValidationError) as exc:
        ImageClassificationDatasetReleaseSerializer.validate(ser, {"dataset": SimpleNamespace(name="ds")})
    assert "dataset_file" in exc.value.detail

    existing = SimpleNamespace(status="ready", pk=1, name="ds")
    qs = type("QS", (), {"exclude": lambda self, **k: self, "first": lambda self: existing})()
    with patch(
        "apps.mlops.serializers.image_classification.ImageClassificationDatasetRelease._default_manager.filter",
        return_value=qs,
    ):
        with pytest.raises(serializers.ValidationError) as dup:
            ImageClassificationDatasetReleaseSerializer.validate(
                ser,
                {"dataset": SimpleNamespace(name="ds"), "version": "v1.0.0", "dataset_file": "zip"},
            )
        assert "已存在" in str(dup.value.detail["version"])


def test_train_job_hyperopt_and_serving_ports():
    job_ser = ImageClassificationTrainJobSerializer.__new__(ImageClassificationTrainJobSerializer)
    with pytest.raises(serializers.ValidationError, match="必须是字典格式"):
        ImageClassificationTrainJobSerializer.validate_hyperopt_config(job_ser, [])
    with pytest.raises(serializers.ValidationError, match="必须包含 hyperparams"):
        ImageClassificationTrainJobSerializer.validate_hyperopt_config(job_ser, {"epochs": 1})
    with pytest.raises(serializers.ValidationError, match="hyperparams 必须是字典"):
        ImageClassificationTrainJobSerializer.validate_hyperopt_config(job_ser, {"hyperparams": []})
    assert ImageClassificationTrainJobSerializer.validate_hyperopt_config(
        job_ser, {"hyperparams": {"lr": 0.1}}
    ) == {"hyperparams": {"lr": 0.1}}

    job_ser.parent = None
    job_ser._context = {}
    assert ImageClassificationTrainJobSerializer.get_config_url_display(job_ser, SimpleNamespace(config_url=None)) is None
    request = SimpleNamespace(build_absolute_uri=lambda url: f"http://x{url}")
    job_ser._context = {"request": request}
    obj = SimpleNamespace(config_url=SimpleNamespace(url="/cfg.json"))
    assert ImageClassificationTrainJobSerializer.get_config_url_display(job_ser, obj) == "http://x/cfg.json"

    serving = ImageClassificationServingSerializer.__new__(ImageClassificationServingSerializer)
    assert ImageClassificationServingSerializer.get_actual_port(serving, SimpleNamespace(container_info=None, port=8080)) == 8080
    assert ImageClassificationServingSerializer.get_actual_port(
        serving, SimpleNamespace(container_info={"port": 9000}, port=8080)
    ) == 9000
    assert ImageClassificationServingSerializer.get_container_status(serving, SimpleNamespace(container_info=None)) == "unknown"
    assert ImageClassificationServingSerializer.get_container_status(
        serving, SimpleNamespace(container_info={"status": "running"})
    ) == "running"
    assert ImageClassificationServingSerializer.validate_model_version(serving, "latest") == "latest"
    assert ImageClassificationServingSerializer.validate_model_version(serving, "3") == "3"
    with pytest.raises(serializers.ValidationError, match="必须是 'latest' 或正整数"):
        ImageClassificationServingSerializer.validate_model_version(serving, "v1")
