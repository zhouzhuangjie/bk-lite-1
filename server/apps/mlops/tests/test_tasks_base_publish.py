"""mlops.tasks.base：样本计数、元数据拼装、发布失败标记与已结束任务短路。"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.mlops.tasks.base import (
    DatasetPublishConfig,
    build_base_metadata,
    count_csv_samples,
    count_txt_samples,
    mark_release_as_failed,
    publish_dataset_release_base,
)

pytestmark = pytest.mark.django_db


def test_count_csv_and_txt_samples(tmp_path: Path):
    csv_path = tmp_path / "data.csv"
    csv_path.write_bytes(b"h1,h2\na,1\nb,2\n")
    assert count_csv_samples(csv_path) == 2
    empty_csv = tmp_path / "empty.csv"
    empty_csv.write_bytes(b"")
    assert count_csv_samples(empty_csv) == 0

    txt_path = tmp_path / "rows.txt"
    txt_path.write_bytes(b"one\ntwo\nthree")
    assert count_txt_samples(txt_path) == 3
    trailing = tmp_path / "trail.txt"
    trailing.write_bytes(b"one\ntwo\n")
    assert count_txt_samples(trailing) == 2
    blank = tmp_path / "blank.txt"
    blank.write_bytes(b"")
    assert count_txt_samples(blank) == 0


def test_build_base_metadata_merges_extra_and_source_names():
    train = SimpleNamespace(name="train.csv")
    val = SimpleNamespace(name="val.csv")
    test = SimpleNamespace(name="test.csv")
    meta = build_base_metadata(
        10,
        4,
        2,
        train,
        val,
        test,
        1,
        2,
        3,
        extra_fields={"classes": 5},
    )
    assert meta["train_samples"] == 10
    assert meta["val_samples"] == 4
    assert meta["test_samples"] == 2
    assert meta["total_samples"] == 16
    assert meta["classes"] == 5
    assert meta["source"] == {
        "type": "manual_selection",
        "train_file_id": 1,
        "val_file_id": 2,
        "test_file_id": 3,
        "train_file_name": "train.csv",
        "val_file_name": "val.csv",
        "test_file_name": "test.csv",
    }


def test_mark_release_as_failed_updates_status_and_handles_missing():
    release = SimpleNamespace(status="processing", metadata={})
    saved = []

    def _save(update_fields):
        saved.append(list(update_fields))

    release.save = _save

    class _DoesNotExist(Exception):
        pass

    class _QS:
        def get(self, id):
            if id == 7:
                return release
            raise FakeRelease.DoesNotExist()

    class FakeRelease:
        DoesNotExist = _DoesNotExist
        objects = _QS()

    assert mark_release_as_failed(FakeRelease, 7, "任务超时") is True
    assert release.status == "failed"
    assert release.metadata["error"] == "任务超时"
    assert "failed_at" in release.metadata
    assert saved == [["status", "metadata"]]
    assert mark_release_as_failed(FakeRelease, 99) is False

    class _BoomQS:
        def get(self, id):
            raise RuntimeError("db down")

    FakeRelease.objects = _BoomQS()
    assert mark_release_as_failed(FakeRelease, 7) is False


@pytest.mark.django_db
def test_publish_dataset_release_base_skips_already_finished():
    release = SimpleNamespace(id=3, status="published")

    class _QS:
        def select_for_update(self):
            return self

        def get(self, id):
            assert id == 3
            return release

    class FakeRelease:
        objects = _QS()

    config = DatasetPublishConfig(
        release_model=FakeRelease,
        train_data_model=MagicMock(),
        task_type="classification",
        file_extension="csv",
        storage_prefix="classification_datasets",
        count_samples=lambda _p: 0,
        build_metadata=lambda *args, **kwargs: {},
    )
    out = publish_dataset_release_base(config, 3, 1, 2, 3)
    assert out == {"result": False, "reason": "Task already published"}
    assert release.status == "published"
