"""CollectCredentialResultService：Stargazer 凭据回写必须落到 hit-state，缺字段拒绝。"""
from unittest.mock import MagicMock

import pytest

from apps.cmdb.services.collect_credential_result_service import CollectCredentialResultService

pytestmark = pytest.mark.unit


@pytest.fixture
def hit_state(monkeypatch):
    svc = MagicMock()
    monkeypatch.setattr(
        "apps.cmdb.services.collect_credential_result_service.CollectHitStateService",
        svc,
    )
    return svc


def test_process_result_rejects_missing_task_or_host(hit_state):
    assert CollectCredentialResultService.process_result({})["result"] is False
    assert CollectCredentialResultService.process_result({"collect_task_id": 1})["result"] is False
    assert CollectCredentialResultService.process_result({"task_id": 1, "host": "10.0.0.1"})["result"] is False
    hit_state.mark_success.assert_not_called()
    hit_state.mark_failure.assert_not_called()


def test_process_result_marks_success_with_host_snapshot(hit_state):
    result = CollectCredentialResultService.process_result(
        {
            "collect_task_id": 9,
            "host": " 10.0.0.8 ",
            "credential_id": "cred-1",
            "success": True,
            "snapshot": {"os": "linux"},
        }
    )
    assert result == {
        "result": True,
        "task_id": 9,
        "object_key": "host:10.0.0.8",
        "credential_id": "cred-1",
    }
    hit_state.mark_success.assert_called_once()
    args = hit_state.mark_success.call_args.args
    assert args[0] == 9
    assert args[1] == "host:10.0.0.8"
    assert args[2] == "cred-1"
    assert args[3]["host"] == "10.0.0.8"
    assert args[3]["os"] == "linux"


def test_process_result_marks_failure_with_default_kind(hit_state):
    result = CollectCredentialResultService.process_result(
        {
            "task_id": "t1",
            "host": "h1",
            "credential_id": "c1",
            "success": False,
            "error_message": "auth failed",
        }
    )
    assert result["result"] is True
    hit_state.mark_failure.assert_called_once()
    args = hit_state.mark_failure.call_args.args
    assert args[4] == "task"
    assert args[5] == "auth failed"


def test_process_batch_aggregates_events_and_preserves_next_since(hit_state):
    payload = {
        "next_since": "cursor-9",
        "events": [
            {"collect_task_id": 1, "host": "h1", "credential_id": "c1", "success": True},
            {"host": "missing-task"},
            {"collect_task_id": 1, "host": "h2", "credential_id": "c2", "success": False, "failure_kind": "timeout"},
        ],
    }
    result = CollectCredentialResultService.process_batch(payload)
    assert result["processed"] == 2
    assert result["failed"] == 1
    assert result["result"] is False
    assert result["next_since"] == "cursor-9"
    assert hit_state.mark_success.call_count == 1
    assert hit_state.mark_failure.call_count == 1


def test_process_batch_falls_back_to_single_event_when_events_missing(hit_state):
    result = CollectCredentialResultService.process_batch(
        {"collect_task_id": 3, "host": "h", "credential_id": "c", "success": True}
    )
    assert result["result"] is True
    assert result["task_id"] == 3
