"""installer 任务：事件解析、步骤推进、异常结构化、连通目标匹配。

对照下发契约：非 BKINSTALL_EVENT 行忽略；非法 JSON 不中断；running 事件写入步骤；
Go 错误 JSON 提取 exit_code/timeout；连通确认按 install_node_id 优先于 IP。
"""
import json
from types import SimpleNamespace

import pytest

from apps.node_mgmt.constants.installer import InstallerConstants
from apps.node_mgmt.tasks import installer as installer_tasks

pytestmark = pytest.mark.unit


class _DummyNode:
    def __init__(self, result=None, status="running", cpu_architecture="amd64", ip="10.0.0.1"):
        self.result = result or {}
        self.status = status
        self.cpu_architecture = cpu_architecture
        self.ip = ip
        self.saved = []

    def save(self, update_fields=None):
        self.saved.append(list(update_fields or []))


def _event_line(step, status, **extra):
    payload = {"step": step, "status": status, **extra}
    return f"{installer_tasks.INSTALLER_EVENT_PREFIX}{json.dumps(payload)}"


def test_parse_installer_events_ignores_noise_and_bad_json():
    text = "\n".join(
        [
            "",
            "plain log line",
            f"{installer_tasks.INSTALLER_EVENT_PREFIX}",
            f"{installer_tasks.INSTALLER_EVENT_PREFIX}{{not json",
            _event_line("download_package", "running", message="start"),
            _event_line("download_package", "success", message="done"),
        ]
    )
    events = installer_tasks._parse_installer_events(text)
    assert [e["status"] for e in events] == ["running", "success"]
    assert installer_tasks._parse_installer_events("") == []
    assert installer_tasks._parse_installer_events(None) == []


def test_apply_installer_events_records_running_then_success():
    node = _DummyNode()
    text = "\n".join(
        [
            _event_line("download_package", "running", message="downloading"),
            _event_line("download_package", "success", message="downloaded"),
        ]
    )
    assert installer_tasks._apply_installer_events_to_node(node, text) is True
    steps = node.result["steps"]
    assert steps
    assert any(step.get("action") == "download" for step in steps)
    assert "installer_progress" in node.result
    assert installer_tasks._apply_installer_events_to_node(node, "no events") is False


def test_execution_attempt_and_connectivity_target():
    node = SimpleNamespace(result={})
    assert installer_tasks._get_execution_attempt(node) == 1
    node.result = {InstallerConstants.EXECUTION_ATTEMPT_KEY: 3}
    assert installer_tasks._get_execution_attempt(node) == 3
    node.result = {InstallerConstants.EXECUTION_ATTEMPT_KEY: 0}
    assert installer_tasks._get_execution_attempt(node) == 1

    task = SimpleNamespace(result={InstallerConstants.INSTALL_NODE_ID_KEY: "n-1"}, ip="10.0.0.8")
    assert installer_tasks._matches_install_connectivity_target(task, "n-1") is True
    assert installer_tasks._matches_install_connectivity_target(task, "n-2") is False
    task_ip = SimpleNamespace(result={}, ip="10.0.0.8")
    assert installer_tasks._matches_install_connectivity_target(task_ip, "n-x", node_ip="10.0.0.8") is True
    assert installer_tasks._matches_install_connectivity_target(task_ip, "n-x", node_ip="10.0.0.9") is False


def test_parse_exception_details_extracts_go_error_fields():
    err = Exception('remote failed {"success": false, "error": "command execution failed: exit code 2 timed out", "result": "boom", "instance_id": "i-1"}')
    details = installer_tasks._parse_exception_details("failed", err)
    assert details["instance_id"] == "i-1"
    assert details["exit_code"] == 2
    assert details["error_type"] in {"timeout", "execution"}
    assert details["command_output"] == "boom"

    plain = installer_tasks._parse_exception_details("just failed", None)
    assert plain["exception_type"] == "Unknown"
    assert plain["error_message"] == "just failed"


def test_collect_failure_context_from_latest_installer_step():
    node = _DummyNode(
        result={
            "steps": [
                {"action": "download", "details": {"note": "skip"}},
                {
                    "action": "install",
                    "details": {
                        "installer_event": True,
                        "bucket": "bklite",
                        "file_key": "linux/amd64/pkg.tgz",
                        "package_name": "controller",
                    },
                },
            ]
        },
        cpu_architecture="amd64",
    )
    ctx = installer_tasks._collect_failure_context_from_node(node)
    assert ctx["bucket"] == "bklite"
    assert ctx["file_key"] == "linux/amd64/pkg.tgz"
    assert ctx["cpu_architecture"] == "amd64"


def test_save_node_result_and_pending_connectivity_set_phase():
    node = _DummyNode(result={"steps": []})
    installer_tasks._save_node_result(node, InstallerConstants.OVERALL_STATUS_SUCCESS, "ok")
    assert node.result[InstallerConstants.EXECUTION_PHASE_KEY] == InstallerConstants.EXECUTION_PHASE_FINISHED
    assert node.status == "success"

    pending = _DummyNode(result={"steps": []})
    installer_tasks._save_node_pending_connectivity(pending, "wait sidecar")
    assert pending.result[InstallerConstants.EXECUTION_PHASE_KEY] == InstallerConstants.EXECUTION_PHASE_CONNECTIVITY_WAITING
    assert pending.status == InstallerConstants.STEP_STATUS_RUNNING


def test_get_execution_phase_and_build_step():
    node = SimpleNamespace(result={InstallerConstants.EXECUTION_PHASE_KEY: "bootstrap_running"})
    assert installer_tasks._get_execution_phase(node) == "bootstrap_running"
    step = installer_tasks._build_step("download", "running", "start")
    assert step["action"] == "download"
    assert step["status"] == "running"
    assert step["message"] == "start"


def test_batch_add_and_advance_and_update_steps():
    n1 = _DummyNode(result={"steps": []})
    n2 = _DummyNode(result={"steps": []})
    installer_tasks._batch_add_step([n1, n2], "download_package", "running", "start")
    assert n1.result["steps"][-1]["action"] == "download_package"
    assert n2.result["steps"][-1]["status"] == "running"
    installer_tasks._batch_advance_step([n1, n2], "success", "done")
    assert n1.result["steps"][-1]["status"] == "success"
    n3 = _DummyNode(result={"steps": [{"action": "install", "status": "running", "message": "go"}]})
    installer_tasks._batch_update_step_status([n3], "failed", "boom")
    assert n3.result["steps"][-1]["status"] == "failed"
    assert "boom" in n3.result["steps"][-1]["message"] or n3.result["steps"][-1].get("message") == "boom"

