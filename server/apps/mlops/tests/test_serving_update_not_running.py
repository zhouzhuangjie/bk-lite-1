"""Serving.update：容器非 running 时只写库、不重启。"""
from unittest.mock import MagicMock

import pytest
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.mlops.models.image_classification import ImageClassificationTrainJob, ImageClassificationServing
from apps.mlops.models.object_detection import ObjectDetectionTrainJob
from apps.mlops.views.image_classification import ImageClassificationServingViewSet
from apps.mlops.views.object_detection import ObjectDetectionServingViewSet
from .conftest import create_object_detection_serving, create_train_job

pytestmark = [pytest.mark.django_db, pytest.mark.integration]
factory = APIRequestFactory()


def _apply_patch(instance, request):
    for key, value in request.data.items():
        setattr(instance, key, value)
    instance.save()
    return Response({"id": instance.id})


def test_object_detection_update_skips_restart_when_container_not_running(mlops_user, monkeypatch):
    mlops_user.permission["mlops"].add("object_detection-Edit")
    train_job = create_train_job(ObjectDetectionTrainJob, team=1)
    serving = create_object_detection_serving(
        train_job,
        team=1,
        status_value="inactive",
        container_info={"state": "exited", "port": 3000},
    )
    webhook_remove = MagicMock(side_effect=AssertionError("不应重启已停止容器"))
    monkeypatch.setattr("apps.mlops.views.object_detection.WebhookClient.remove", webhook_remove)
    monkeypatch.setattr(
        "apps.core.utils.viewset_utils.AuthViewSet.update",
        lambda self, request, *a, **k: _apply_patch(serving, request),
    )

    request = factory.patch(
        f"/api/v1/mlops/object_detection_servings/{serving.id}/",
        {"name": "serving-renamed", "model_version": "2"},
        format="json",
    )
    force_authenticate(request, user=mlops_user)
    monkeypatch.setattr(ObjectDetectionServingViewSet, "get_object", lambda self: serving)
    resp = ObjectDetectionServingViewSet.as_view({"patch": "update"})(request, pk=serving.id)
    assert resp.status_code == 200
    serving.refresh_from_db()
    assert serving.name == "serving-renamed"
    assert serving.model_version == "2"
    webhook_remove.assert_not_called()
    assert serving.container_info.get("state") == "exited"


def test_image_classification_update_skips_restart_when_container_not_running(mlops_user, monkeypatch):
    mlops_user.permission["mlops"].add("image_classification-Edit")
    train_job = create_train_job(ImageClassificationTrainJob, team=1)
    serving = ImageClassificationServing.objects.create(
        name="ic-serving",
        description="",
        team=[1],
        train_job=train_job,
        model_version="latest",
        status="inactive",
        container_info={},
    )
    webhook_remove = MagicMock(side_effect=AssertionError("空 container_info 不应重启"))
    monkeypatch.setattr("apps.mlops.views.image_classification.WebhookClient.remove", webhook_remove)
    monkeypatch.setattr(
        "apps.core.utils.viewset_utils.AuthViewSet.update",
        lambda self, request, *a, **k: _apply_patch(serving, request),
    )

    request = factory.patch(
        f"/api/v1/mlops/image_classification_servings/{serving.id}/",
        {"description": "only-db"},
        format="json",
    )
    force_authenticate(request, user=mlops_user)
    monkeypatch.setattr(ImageClassificationServingViewSet, "get_object", lambda self: serving)
    resp = ImageClassificationServingViewSet.as_view({"patch": "update"})(request, pk=serving.id)
    assert resp.status_code == 200
    serving.refresh_from_db()
    assert serving.description == "only-db"
    webhook_remove.assert_not_called()
