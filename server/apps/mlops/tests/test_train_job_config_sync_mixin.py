"""TrainJobConfigSyncMixin：完整配置装配、跳过非配置字段、MinIO 失败回滚。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.mlops.models.log_clustering import LogClusteringTrainJob
from apps.mlops.models.mixins import ConfigSyncError

pytestmark = pytest.mark.django_db


def test_build_complete_config_injects_model_mlflow_and_max_evals():
    job = LogClusteringTrainJob(name="lc-job", algorithm="drain", max_evals=12, hyperopt_config={})
    job.pk = 88
    config = job._build_complete_config()
    assert config["hyperparams"]["max_evals"] == 12
    assert config["model"] == {"type": "drain", "name": "LogClustering_drain_88"}
    assert config["mlflow"] == {"experiment_name": "LogClustering_drain_88"}


def test_save_skips_minio_when_update_fields_are_unrelated():
    job = LogClusteringTrainJob(name="lc-skip", algorithm="drain", max_evals=3, hyperopt_config={"a": 1}, team=[1])
    with (
        patch.object(LogClusteringTrainJob, "_sync_config_to_minio") as sync,
        patch("django.db.models.base.Model.save"),
    ):
        job.save(update_fields=["status"])
    sync.assert_not_called()


def test_sync_config_to_minio_wraps_upload_failure():
    job = LogClusteringTrainJob(name="lc-fail", algorithm="drain", max_evals=3, hyperopt_config={"a": 1}, team=[1])
    job.pk = 9
    job.config_url = MagicMock()
    job.config_url.name = "old.json"
    job.config_url.save.side_effect = OSError("minio down")
    with pytest.raises(ConfigSyncError, match="训练配置同步到 MinIO 失败，数据库变更已回滚"):
        job._sync_config_to_minio()


def test_sync_config_to_minio_deletes_old_file_after_upload():
    job = LogClusteringTrainJob(name="lc-ok", algorithm="drain", max_evals=3, hyperopt_config={"a": 1}, team=[1])
    job.pk = 10
    storage = MagicMock()
    file_field = MagicMock()
    file_field.name = "old.json"
    file_field.storage = storage

    def _save(filename, content, save=False):
        file_field.name = filename

    file_field.save.side_effect = _save
    job.config_url = file_field
    job._sync_config_to_minio()
    storage.delete.assert_called_once_with("old.json")
    assert file_field.name.startswith("config_10_")
    assert file_field.name.endswith(".json")


def test_sync_config_to_minio_swallows_old_file_delete_error():
    job = LogClusteringTrainJob(name="lc-del-fail", algorithm="drain", max_evals=3, hyperopt_config={"a": 1}, team=[1])
    job.pk = 11
    storage = MagicMock()
    storage.delete.side_effect = OSError("minio delete")
    file_field = MagicMock()
    file_field.name = "old.json"
    file_field.storage = storage

    def _save(filename, content, save=False):
        file_field.name = filename

    file_field.save.side_effect = _save
    job.config_url = file_field
    job._sync_config_to_minio()
    storage.delete.assert_called_once_with("old.json")
    assert file_field.name.startswith("config_11_")

