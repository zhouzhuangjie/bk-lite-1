"""TrainDataFileCleanupMixin / TrainJob.save：替换文件清理、空配置删 MinIO。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.mlops.models.log_clustering import LogClusteringTrainJob
from apps.mlops.models.mixins import TrainDataFileCleanupMixin

pytestmark = pytest.mark.django_db


class _Parent:
    def save(self, *args, **kwargs):
        self.saved = True


class _DummyCleanup(TrainDataFileCleanupMixin, _Parent):
    DoesNotExist = type("DoesNotExist", (Exception,), {})
    _file_field_name = "train_data"

    def __init__(self, pk, old_name, new_name, delete_side_effect=None, get_side_effect=None):
        self.pk = pk
        self.saved = False
        self.train_data = MagicMock()
        self.train_data.name = new_name
        old_file = MagicMock()
        old_file.name = old_name
        if delete_side_effect:
            old_file.delete.side_effect = delete_side_effect
        self._old_file = old_file
        self._get_side_effect = get_side_effect

        dummy = self

        class _QS:
            def select_for_update(self_qs):
                return self_qs

            def get(self_qs, pk):
                if dummy._get_side_effect:
                    raise dummy._get_side_effect
                return SimpleNamespace(train_data=dummy._old_file)

        type(self).objects = _QS()


def test_train_data_cleanup_deletes_old_file_when_path_changes():
    obj = _DummyCleanup(pk=1, old_name="old.csv", new_name="new.csv")
    obj.save()
    obj._old_file.delete.assert_called_once_with(save=False)
    assert obj.saved is True


def test_train_data_cleanup_swallows_delete_and_lookup_errors():
    delete_fail = _DummyCleanup(pk=2, old_name="old.csv", new_name="new.csv", delete_side_effect=OSError("minio"))
    delete_fail.save()
    assert delete_fail.saved is True

    missing = _DummyCleanup(pk=3, old_name="old.csv", new_name="new.csv", get_side_effect=_DummyCleanup.DoesNotExist())
    missing.save()
    assert missing.saved is True

    boom = _DummyCleanup(pk=4, old_name="old.csv", new_name="new.csv", get_side_effect=RuntimeError("locked"))
    boom.save()
    assert boom.saved is True

    same = _DummyCleanup(pk=5, old_name="same.csv", new_name="same.csv")
    same.save()
    same._old_file.delete.assert_not_called()


@pytest.mark.django_db
def test_train_job_save_deletes_minio_when_config_empty():
    job = LogClusteringTrainJob(name="empty-cfg", algorithm="drain", max_evals=1, hyperopt_config={}, team=[1])
    job.pk = 21
    file_field = MagicMock()
    file_field.name = "old.json"
    job.config_url = file_field
    update = MagicMock()
    with (
        patch("django.db.models.base.Model.save"),
        patch.object(LogClusteringTrainJob.objects, "filter", return_value=SimpleNamespace(update=update)),
    ):
        job.save()
    file_field.delete.assert_called_once_with(save=False)
    assert not job.config_url
    update.assert_called_once()


@pytest.mark.django_db
def test_train_job_save_syncs_when_hyperopt_config_present():
    job = LogClusteringTrainJob(name="has-cfg", algorithm="drain", max_evals=1, hyperopt_config={"a": 1}, team=[1])
    job.pk = 22
    job.config_url = MagicMock()
    update = MagicMock()
    with (
        patch("django.db.models.base.Model.save"),
        patch.object(LogClusteringTrainJob, "_sync_config_to_minio") as sync,
        patch.object(LogClusteringTrainJob.objects, "filter", return_value=SimpleNamespace(update=update)),
    ):
        job.save()
    sync.assert_called_once()
    update.assert_called_once()
