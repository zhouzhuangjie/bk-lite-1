"""目标检测序列化器：YOLO metadata / 版本号 / hyperopt 配置校验契约。"""
import pytest
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.mlops.serializers.object_detection import (
    ObjectDetectionDatasetReleaseSerializer,
    ObjectDetectionTrainDataSerializer,
    ObjectDetectionTrainJobSerializer,
)

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()


def _serializer(cls, query=""):
    user = UserFactory(is_superuser=True)
    user.group_list = [{"id": 1, "name": "T1"}]
    django_req = factory.get(f"/{query}")
    django_req.COOKIES = {"current_team": "1"}
    force_authenticate(django_req, user=user)
    request = Request(django_req)
    request.user = user
    return cls(context={"request": request})


def _valid_metadata(**overrides):
    payload = {
        "format": "YOLO",
        "classes": ["cat"],
        "num_classes": 1,
        "num_images": 1,
        "labels": {
            "a.jpg": [
                {
                    "class_id": 0,
                    "class_name": "cat",
                    "x_center": 0.5,
                    "y_center": 0.5,
                    "width": 0.2,
                    "height": 0.2,
                }
            ]
        },
    }
    payload.update(overrides)
    return payload


def test_train_data_metadata_allows_empty_and_rejects_invalid_shape():
    ser = _serializer(ObjectDetectionTrainDataSerializer)
    assert ser.validate_metadata(None) is None
    assert ser.validate_metadata({}) == {}
    with pytest.raises(ValidationError, match="字典"):
        ser.validate_metadata(["not-dict"])
    with pytest.raises(ValidationError, match="缺少必需字段"):
        ser.validate_metadata({"format": "YOLO"})
    with pytest.raises(ValidationError, match="YOLO"):
        ser.validate_metadata(_valid_metadata(format="COCO"))


def test_train_data_metadata_validates_classes_and_counts():
    ser = _serializer(ObjectDetectionTrainDataSerializer)
    with pytest.raises(ValidationError, match="classes 必须是数组"):
        ser.validate_metadata(_valid_metadata(classes="cat"))
    with pytest.raises(ValidationError, match="classes 不能为空"):
        ser.validate_metadata(_valid_metadata(classes=[], num_classes=0))
    with pytest.raises(ValidationError, match="字符串"):
        ser.validate_metadata(_valid_metadata(classes=[1]))
    with pytest.raises(ValidationError, match="正整数"):
        ser.validate_metadata(_valid_metadata(num_classes=0))
    with pytest.raises(ValidationError, match="不匹配"):
        ser.validate_metadata(_valid_metadata(num_classes=2))
    with pytest.raises(ValidationError, match="num_images"):
        ser.validate_metadata(_valid_metadata(num_images=0))


def test_train_data_metadata_validates_labels_and_bbox():
    ser = _serializer(ObjectDetectionTrainDataSerializer)
    with pytest.raises(ValidationError, match="labels 必须是对象"):
        ser.validate_metadata(_valid_metadata(labels=[]))
    with pytest.raises(ValidationError, match="标注必须是数组"):
        ser.validate_metadata(_valid_metadata(labels={"a.jpg": {"class_id": 0}}))
    with pytest.raises(ValidationError, match="标注必须是对象"):
        ser.validate_metadata(_valid_metadata(labels={"a.jpg": ["box"]}))
    with pytest.raises(ValidationError, match="缺少字段"):
        ser.validate_metadata(_valid_metadata(labels={"a.jpg": [{"class_id": 0}]}))
    bad_id = _valid_metadata()
    bad_id["labels"]["a.jpg"][0]["class_id"] = 3
    with pytest.raises(ValidationError, match="超出范围"):
        ser.validate_metadata(bad_id)
    bad_name = _valid_metadata()
    bad_name["labels"]["a.jpg"][0]["class_name"] = "dog"
    with pytest.raises(ValidationError, match="class_name"):
        ser.validate_metadata(bad_name)
    bad_coord = _valid_metadata()
    bad_coord["labels"]["a.jpg"][0]["x_center"] = 1.5
    with pytest.raises(ValidationError, match="x_center"):
        ser.validate_metadata(bad_coord)


def test_train_data_metadata_accepts_valid_yolo_and_optional_statistics():
    ser = _serializer(ObjectDetectionTrainDataSerializer)
    payload = _valid_metadata(
        statistics={"total_annotations": 1, "class_distribution": {"cat": 1}},
    )
    assert ser.validate_metadata(payload)["format"] == "YOLO"
    with pytest.raises(ValidationError, match="statistics 必须是对象"):
        ser.validate_metadata(_valid_metadata(statistics=[]))
    with pytest.raises(ValidationError, match="total_annotations"):
        ser.validate_metadata(_valid_metadata(statistics={"total_annotations": -1}))
    with pytest.raises(ValidationError, match="class_distribution"):
        ser.validate_metadata(_valid_metadata(statistics={"class_distribution": []}))


def test_dataset_release_version_must_match_semver():
    ser = _serializer(ObjectDetectionDatasetReleaseSerializer)
    assert ser.validate_version("v1.0.0") == "v1.0.0"
    with pytest.raises(ValidationError, match="vX.Y.Z"):
        ser.validate_version("1.0.0")


def test_train_job_hyperopt_config_requires_hyperparams_dict():
    ser = _serializer(ObjectDetectionTrainJobSerializer)
    with pytest.raises(ValidationError, match="字典格式"):
        ser.validate_hyperopt_config("x")
    with pytest.raises(ValidationError, match="hyperparams"):
        ser.validate_hyperopt_config({})
    with pytest.raises(ValidationError, match="hyperparams 必须是字典"):
        ser.validate_hyperopt_config({"hyperparams": []})
    assert ser.validate_hyperopt_config({"hyperparams": {"epochs": 10}})["hyperparams"]["epochs"] == 10
