"""CollectDispatchService 剩余派发：分类、合并、单目标执行与空计划。"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.cmdb.constants.constants import CollectPluginTypes
from apps.cmdb.services.collect_dispatch_service import CollectDispatchService, DispatchAttemptResult
from apps.cmdb.services.collect_target_service import CanonicalCollectTarget

pytestmark = pytest.mark.unit


def _task(**kwargs):
    defaults = dict(
        task_type=CollectPluginTypes.HOST,
        is_job=True,
        credential=[{"credential_id": "c1"}, {"credential_id": "c2"}],
        decrypt_credentials=[{"credential_id": "c1"}, {"credential_id": "c2"}],
        instances=[],
        ip_range="",
        id=7,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _target(host="10.0.0.1", instance_id="host-1"):
    return CanonicalCollectTarget(
        task_id=7,
        task_type=CollectPluginTypes.HOST,
        executor="job",
        model_id="host",
        host=host,
        instance_id=instance_id,
        snapshot={"_id": instance_id, "ip": host, "inst_name": host, "model_id": "host"},
    )


def test_should_dispatch_requires_multi_credential_and_supported_type():
    assert CollectDispatchService.should_dispatch(_task()) is True
    assert CollectDispatchService.should_dispatch(_task(decrypt_credentials=[{"credential_id": "c1"}])) is False
    assert CollectDispatchService.should_dispatch(_task(task_type="unknown")) is False


def test_classify_failure_kind_and_extract_error():
    assert CollectDispatchService._classify_failure_kind("auth failed") == "credential"
    assert CollectDispatchService._classify_failure_kind("timeout") == "task"
    assert CollectDispatchService._extract_error_message("x") == ""
    assert CollectDispatchService._extract_error_message({"add": [{"_error": "denied"}]}) == "denied"
    assert CollectDispatchService._extract_error_message({"add": [{}], "update": []}) == ""


def test_classify_payload_success_config_file_and_rows():
    task = _task(task_type=CollectPluginTypes.CONFIG_FILE)
    ok, err = CollectDispatchService._classify_payload_success(task, {"config_file": {"status": "pending"}}, {})
    assert ok is True and err == ""

    host_task = _task()
    ok, err = CollectDispatchService._classify_payload_success(
        host_task, {}, {"add": [{"_status": "success"}]}
    )
    assert ok is True
    ok, err = CollectDispatchService._classify_payload_success(host_task, {}, {"__raw_data__": [{"a": 1}]})
    assert ok is True
    ok, err = CollectDispatchService._classify_payload_success(
        host_task, {}, {"add": [{"_status": "failed", "_error": "password denied"}]}
    )
    assert ok is False
    assert err == "password denied"


def test_deep_merge_dict_merges_nested_and_lists():
    left = {"host": {"a": {"ok": 1}}, "ips": [1]}
    right = {"host": {"a": {"fail": 0}, "b": 2}, "ips": [2], "extra": True}
    merged = CollectDispatchService._deep_merge_dict(left, right)
    assert merged["host"]["a"] == {"ok": 1, "fail": 0}
    assert merged["host"]["b"] == 2
    assert merged["ips"] == [1, 2]
    assert merged["extra"] is True


def test_build_task_override_clears_ip_range_for_instance():
    task = _task(ip_range="10.0.0.0/24", instances=[{"old": 1}])
    target = _target()
    override = CollectDispatchService._build_task_override(task, {"credential_id": "c1"}, target)
    assert override.credential == {"credential_id": "c1"}
    assert override.instances == [target.snapshot]
    assert override.ip_range == ""
    range_target = _target(instance_id="")
    override2 = CollectDispatchService._build_task_override(task, {"credential_id": "c1"}, range_target)
    assert override2.instances == []
    assert override2.ip_range == range_target.host


def test_run_single_target_exception_and_success(monkeypatch):
    task = _task()
    target = _target()

    class Boom:
        def __init__(self, task):
            self.task = task

        def main(self):
            raise RuntimeError("login denied")

    failed = CollectDispatchService._run_single_target(task, {"credential_id": "c1"}, target, Boom)
    assert failed.success is False
    assert failed.failure_kind == "credential"
    assert failed.error_message == "login denied"

    class Ok:
        def __init__(self, task):
            self.task = task

        def main(self):
            return {"host": {"ok": True}}, {"add": [{"_status": "success"}]}

    ok = CollectDispatchService._run_single_target(task, {"credential_id": "c1"}, target, Ok)
    assert ok.success is True
    assert ok.raw_payload["collect_data"] == {"host": {"ok": True}}


def test_merge_attempt_results_config_file_pending(monkeypatch):
    task = _task(task_type=CollectPluginTypes.CONFIG_FILE)
    monkeypatch.setattr(
        "apps.cmdb.services.config_file_service.ConfigFileService.build_pending_result",
        lambda t: ({"config_file": {"status": "pending"}}, {"message": "等待回传"}),
    )
    collect, fmt = CollectDispatchService.merge_attempt_results(
        task,
        [DispatchAttemptResult("k", "c1", True, "", raw_payload={})],
    )
    assert collect == {"config_file": {"status": "pending"}}
    assert fmt["message"] == "等待回传"


def test_merge_attempt_results_keeps_last_success_per_object():
    task = _task()
    attempts = [
        DispatchAttemptResult("k1", "c1", False, "credential", "auth"),
        DispatchAttemptResult(
            "k1",
            "c2",
            True,
            "",
            raw_payload={
                "collect_data": {"host": {"a": 1}},
                "format_data": {"add": [{"_status": "ok"}], "update": [], "delete": [], "association": [], "all": 1},
            },
        ),
    ]
    collect, fmt = CollectDispatchService.merge_attempt_results(task, attempts)
    assert collect == {"host": {"a": 1}}
    assert fmt["all"] == 1
    assert fmt["add"][0]["_status"] == "ok"


def test_execute_task_breaks_when_plan_empty(monkeypatch):
    task = _task()
    target = _target()
    monkeypatch.setattr(
        "apps.cmdb.services.collect_target_service.CollectTargetService.build_targets",
        lambda t: [target],
    )
    monkeypatch.setattr(
        "apps.cmdb.services.collect_hit_state_service.CollectHitStateService.list_states",
        lambda task_id: {},
    )
    monkeypatch.setattr(CollectDispatchService, "plan_dispatch", classmethod(lambda cls, *a, **k: {}))
    collect, fmt = CollectDispatchService.execute_task(task)
    assert collect == {}
    assert fmt == {"add": [], "update": [], "delete": [], "association": []}
