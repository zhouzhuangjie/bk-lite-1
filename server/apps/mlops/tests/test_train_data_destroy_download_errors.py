"""图像/目标检测 TrainData：删除失败与下载打开失败返回 500。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from rest_framework import status
from rest_framework.test import APIRequestFactory

from apps.base.tests.factories import UserFactory
from apps.mlops.tests.test_views_actions_param import _call, _model, _view_module

pytestmark = [pytest.mark.django_db, pytest.mark.integration]
factory = APIRequestFactory()

CASES = [
    ("image_classification", "image_classification", "ImageClassification"),
    ("object_detection", "object_detection", "ObjectDetection"),
]


@pytest.fixture
def superuser():
    return UserFactory(username="mlops-td-err", domain="domain.com", roles=[], is_superuser=True)


@pytest.mark.parametrize("suffix,model_module,basename", CASES, ids=[c[0] for c in CASES])
def test_train_data_destroy_generic_exception_returns_500(superuser, suffix, model_module, basename):
    Dataset = _model(model_module, basename, "Dataset")
    TrainData = _model(model_module, basename, "TrainData")
    ds = Dataset.objects.create(name=f"ds-del-{suffix}", description="", team=[1])
    td = TrainData.objects.create(name="td-err", dataset=ds)
    vs = getattr(_view_module(suffix), f"{basename}TrainDataViewSet")
    with patch(f"apps.mlops.views.{suffix}.ModelViewSet.destroy", side_effect=RuntimeError("minio down")):
        resp = _call(vs.as_view({"delete": "destroy"}), factory.delete("/x/"), superuser, pk=td.id)
    assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert "删除失败" in str(resp.data)
    assert "minio down" in str(resp.data)
    assert TrainData.objects.filter(id=td.id).exists()


@pytest.mark.parametrize("suffix,model_module,basename", CASES, ids=[c[0] for c in CASES])
def test_train_data_download_open_failure_returns_500(superuser, suffix, model_module, basename):
    Dataset = _model(model_module, basename, "Dataset")
    TrainData = _model(model_module, basename, "TrainData")
    ds = Dataset.objects.create(name=f"ds-dl-{suffix}", description="", team=[1])
    td = TrainData.objects.create(name="td-dl", dataset=ds)
    vs = getattr(_view_module(suffix), f"{basename}TrainDataViewSet")
    fake_file = MagicMock()
    fake_file.open.side_effect = RuntimeError("read fail")
    fake = SimpleNamespace(train_data=fake_file, name=td.name, id=td.id)
    with patch(f"apps.mlops.views.{suffix}.{basename}TrainDataViewSet.get_object", return_value=fake):
        resp = _call(vs.as_view({"get": "download"}), factory.get("/x/download/"), superuser, pk=td.id)
    assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert "下载失败" in str(resp.data)
    assert "read fail" in str(resp.data)
