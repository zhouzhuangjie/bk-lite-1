"""object/image serving.create CONTAINER_ALREADY_EXISTS；update 运行中容器重启。"""
from unittest.mock import Mock

import pytest
from rest_framework import status

from apps.base.tests.factories import UserFactory
from apps.mlops.tests.test_views_actions_param import (
    ALGOS,
    ALGO_IDS,
    _allow_team_one,
    _call,
    _make_serving,
    _make_train_job,
    _patch_mlflow,
    _view_module,
    factory,
)
from apps.mlops.utils.webhook_client import WebhookError

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@pytest.fixture
def superuser():
    return UserFactory(username="mlops-serve-od", domain="domain.com", roles=[], is_superuser=True)


@pytest.mark.parametrize("suffix,prefix,model_module,basename", ALGOS, ids=ALGO_IDS)
def test_serving_create_container_already_exists_syncs_status(
    monkeypatch, superuser, suffix, prefix, model_module, basename
):
    _allow_team_one(monkeypatch)
    monkeypatch.setattr(
        "apps.core.utils.serializers.get_permission_rules",
        lambda *a, **k: {"team": [1], "instance": []},
    )
    train_job = _make_train_job(model_module, basename)
    mod = _view_module(suffix)
    _patch_mlflow(monkeypatch, suffix)
    monkeypatch.setattr(mod, "get_mlflow_tracking_uri", lambda: "http://mlflow.local")
    monkeypatch.setattr(mod, "get_image_by_prefix", lambda p, algo: "repo/serve:1")

    def serve_conflict(*a, **k):
        raise WebhookError("exists", code="CONTAINER_ALREADY_EXISTS")

    monkeypatch.setattr(mod.WebhookClient, "serve", staticmethod(serve_conflict))
    monkeypatch.setattr(
        mod.WebhookClient,
        "get_status",
        staticmethod(Mock(return_value=[{"id": "synced", "state": "running", "status": "success"}])),
    )
    view = getattr(mod, f"{basename}ServingViewSet").as_view({"post": "create"})
    request = factory.post(
        f"/{suffix}_servings/",
        {"name": "srv", "description": "", "team": [1], "train_job": train_job.id, "model_version": "latest"},
        format="json",
    )
    resp = _call(view, request, superuser)
    assert resp.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED)
    assert resp.data["container_info"]["state"] == "running"
    assert "容器已存在" in resp.data["message"]


@pytest.mark.parametrize(
    "suffix,prefix,model_module,basename",
    [a for a in ALGOS if a[0] in ("object_detection", "image_classification")],
    ids=["object_detection", "image_classification"],
)
def test_image_object_serving_update_restarts_running_container(
    monkeypatch, superuser, suffix, prefix, model_module, basename
):
    _allow_team_one(monkeypatch)
    monkeypatch.setattr(
        "apps.core.utils.serializers.get_permission_rules",
        lambda *a, **k: {"team": [1], "instance": []},
    )
    serving = _make_serving(
        model_module,
        basename,
        container_info={"state": "running", "port": "9000"},
        port=9000,
    )
    mod = _view_module(suffix)
    _patch_mlflow(monkeypatch, suffix)
    monkeypatch.setattr(mod, "get_mlflow_tracking_uri", lambda: "http://mlflow.local")
    monkeypatch.setattr(mod, "get_image_by_prefix", lambda p, algo: "repo/serve:1")
    remove_mock = Mock()
    monkeypatch.setattr(mod.WebhookClient, "remove", staticmethod(remove_mock))
    serve_mock = Mock(return_value={"status": "success", "state": "running", "port": "9100"})
    monkeypatch.setattr(mod.WebhookClient, "serve", staticmethod(serve_mock))
    view = getattr(mod, f"{basename}ServingViewSet").as_view({"put": "update"})
    request = factory.put(
        f"/{suffix}_servings/x/",
        {"name": serving.name, "team": [1], "train_job": serving.train_job_id, "model_version": "2"},
        format="json",
    )
    resp = _call(view, request, superuser, pk=serving.id)
    assert resp.status_code == status.HTTP_200_OK
    remove_mock.assert_called_once()
    serve_mock.assert_called_once()
    serving.refresh_from_db()
    assert serving.container_info["state"] == "running"
    assert serving.model_version == "2"
    assert "重启" in resp.data["message"]


CSV_SERVING_ALGOS = [a for a in ALGOS if a[0] not in ("object_detection", "image_classification")]
CSV_SERVING_IDS = [a[0] for a in CSV_SERVING_ALGOS]


@pytest.mark.parametrize("suffix,prefix,model_module,basename", CSV_SERVING_ALGOS, ids=CSV_SERVING_IDS)
def test_csv_serving_update_restarts_running_container(
    monkeypatch, superuser, suffix, prefix, model_module, basename
):
    _allow_team_one(monkeypatch)
    monkeypatch.setattr(
        "apps.core.utils.serializers.get_permission_rules",
        lambda *a, **k: {"team": [1], "instance": []},
    )
    serving = _make_serving(
        model_module,
        basename,
        container_info={"state": "running", "port": "9000"},
        port=9000,
    )
    mod = _view_module(suffix)
    _patch_mlflow(monkeypatch, suffix)
    monkeypatch.setattr(mod, "get_mlflow_tracking_uri", lambda: "http://mlflow.local")
    monkeypatch.setattr(mod, "get_image_by_prefix", lambda p, algo: "repo/serve:1")
    remove_mock = Mock()
    monkeypatch.setattr(mod.WebhookClient, "remove", staticmethod(remove_mock))
    serve_mock = Mock(return_value={"status": "success", "state": "running", "port": "9100"})
    monkeypatch.setattr(mod.WebhookClient, "serve", staticmethod(serve_mock))
    view = getattr(mod, f"{basename}ServingViewSet").as_view({"put": "update"})
    request = factory.put(
        f"/{suffix}_servings/x/",
        {"name": serving.name, "team": [1], "train_job": serving.train_job_id, "model_version": "2"},
        format="json",
    )
    resp = _call(view, request, superuser, pk=serving.id)
    assert resp.status_code == status.HTTP_200_OK
    remove_mock.assert_called_once()
    serve_mock.assert_called_once()
    serving.refresh_from_db()
    assert serving.container_info["state"] == "running"
    assert serving.model_version == "2"
    assert "重启" in resp.data["message"]


@pytest.mark.parametrize("suffix,prefix,model_module,basename", CSV_SERVING_ALGOS, ids=CSV_SERVING_IDS)
def test_csv_serving_retrieve_webhook_error_degrades(
    monkeypatch, superuser, suffix, prefix, model_module, basename
):
    serving = _make_serving(model_module, basename, container_info={"state": "cached"})
    _allow_team_one(monkeypatch)
    mod = _view_module(suffix)

    def raise_err(ids):
        raise WebhookError("status down")

    monkeypatch.setattr(mod.WebhookClient, "get_status", staticmethod(raise_err))
    view = getattr(mod, f"{basename}ServingViewSet").as_view({"get": "retrieve"})
    request = factory.get(f"/{suffix}_servings/x/")
    resp = _call(view, request, superuser, pk=serving.id)
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["container_info"]["status"] == "error"
    assert resp.data["container_info"].get("_query_failed") is True
    assert "status down" in resp.data["container_info"]["_error"]
