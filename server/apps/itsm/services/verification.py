from __future__ import annotations

import time
import uuid
from typing import Any

from apps.itsm.services.bpmn import build_deployment_archive
from apps.itsm.services.flowable import FlowableClient, variable


class FlowableVerificationError(RuntimeError):
    pass


def _wait_for_tasks(client: FlowableClient, process_id: str, *, assignees: set[str], timeout: float = 10.0) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        tasks = client.active_tasks(process_id)
        if {task["assignee"] for task in tasks} == assignees:
            return tasks
        time.sleep(0.1)
    raise FlowableVerificationError(f"未在限定时间内等到任务集合：{sorted(assignees)}")


def _complete_approval(
    client: FlowableClient,
    task_id: str,
    *,
    intent: str = "complete",
    vote: bool = True,
    sign_users: list[str] | None = None,
    post_users: list[str] | None = None,
) -> None:
    after_users = post_users or []
    receipt_id = uuid.uuid4()
    client.complete_task(
        task_id,
        variables=[
            variable("intent", intent),
            variable("vote", vote),
            variable("hasPost", bool(after_users)),
            variable("postUsers", after_users),
            variable("signUsers", sign_users or []),
            variable(f"itsmReceipt_{receipt_id.hex}", f"verify:{receipt_id}"),
        ],
    )


def verify_flowable_runtime(client: FlowableClient) -> dict[str, Any]:
    unique = uuid.uuid4().hex[:12]
    process_key = f"itsm_verify_{unique}"
    deployment_name = f"bklite-itsm-verification-{unique}"
    config = {
        "schemaVersion": 1,
        "stages": [
            {
                "key": "manager",
                "name": "Manager approval",
                "mode": "serial",
                "approverIds": [101, 102],
                "allowBeforeSign": True,
                "allowAfterSign": True,
            },
            {
                "key": "security",
                "name": "Security countersign",
                "mode": "parallel",
                "approverIds": [201, 202],
                "allowBeforeSign": False,
                "allowAfterSign": False,
            },
        ],
        "handlerIds": [301],
    }
    archive = build_deployment_archive(process_key=process_key, process_name=deployment_name, workflow_config=config)
    deployment = client.deploy_archive(deployment_name, archive, process_key=process_key)
    started = client.start_process(
        deployment["process_definition_id"],
        business_key=f"verify-{unique}",
        variables=[
            variable("approved", True),
            variable("handlerId", "301"),
            variable("approval_manager", ["101", "102"]),
            variable("approval_security", ["201", "202"]),
        ],
    )
    process_id = str(started.get("id") or "")
    if not process_id:
        raise FlowableVerificationError("Flowable 未返回验证流程实例 ID")

    manager_first = _wait_for_tasks(client, process_id, assignees={"101"})[0]
    _complete_approval(client, manager_first["id"], intent="before", vote=False, sign_users=["901"])
    before_sign = _wait_for_tasks(client, process_id, assignees={"901"})[0]
    _complete_approval(client, before_sign["id"])

    manager_reopened = _wait_for_tasks(client, process_id, assignees={"101"})[0]
    _complete_approval(client, manager_reopened["id"], post_users=["902"])
    after_sign = _wait_for_tasks(client, process_id, assignees={"902"})[0]
    _complete_approval(client, after_sign["id"])

    manager_second = _wait_for_tasks(client, process_id, assignees={"102"})[0]
    _complete_approval(client, manager_second["id"])

    parallel = _wait_for_tasks(client, process_id, assignees={"201", "202"})
    for task in parallel:
        _complete_approval(client, task["id"])

    handling = _wait_for_tasks(client, process_id, assignees={"301"})[0]
    handling_receipt_id = uuid.uuid4()
    client.complete_task(
        handling["id"],
        variables=[variable(f"itsmReceipt_{handling_receipt_id.hex}", f"verify:{handling_receipt_id}")],
    )
    if client.process_result(process_id) != "completed":
        raise FlowableVerificationError("验证流程未正常结束")
    return {
        "deployment_id": deployment["deployment_id"],
        "process_definition_id": deployment["process_definition_id"],
        "process_instance_id": process_id,
        "scenarios": ["serial", "parallel", "before_sign", "after_sign", "handling"],
    }
