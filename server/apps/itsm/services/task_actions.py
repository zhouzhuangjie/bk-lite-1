from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.core.utils.user_group import normalize_user_group_ids
from apps.itsm.models import AuditEvent, Command, SignPlan, TaskProjection
from apps.itsm.services.flowable import variable

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ACTIVE_COMMAND_STATUSES = {
    Command.Status.PENDING,
    Command.Status.DELIVERING,
    Command.Status.RETRY,
    Command.Status.UNCERTAIN,
}


class TaskActionConflict(ValueError):
    pass


class TaskActionInvalid(ValueError):
    pass


@dataclass(frozen=True)
class TaskActionResult:
    command: Command
    created: bool
    planned: bool


def _digest(value: dict) -> str:
    content = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _validate_sign_users(user_ids, *, actor_user_id: int, domain: str, team_id: int) -> list[int]:
    if not isinstance(user_ids, list) or not 1 <= len(user_ids) <= 20:
        raise TaskActionInvalid("加签人员数量必须在 1 到 20 之间")
    if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in user_ids):
        raise TaskActionInvalid("加签人员 ID 非法")
    if len(user_ids) != len(set(user_ids)):
        raise TaskActionInvalid("加签人员不能重复")
    if actor_user_id in user_ids:
        raise TaskActionInvalid("不能给自己加签")

    users = list(get_user_model().objects.filter(id__in=user_ids, domain=domain, is_active=True).only("id", "group_list"))
    allowed = {user.id for user in users if team_id in set(normalize_user_group_ids(user.group_list))}
    if allowed != set(user_ids):
        raise TaskActionInvalid("加签人员不属于当前域和组织")
    return user_ids


def enqueue_task_action(
    task_id,
    *,
    request_id: str,
    action: str,
    user_ids: list[int] | None,
    reason: str,
    actor_user_id: int,
    actor_username: str,
    domain: str,
    team_id: int,
) -> TaskActionResult:
    if not isinstance(request_id, str) or not REQUEST_ID_PATTERN.fullmatch(request_id):
        raise TaskActionInvalid("request_id 格式非法")
    if action not in {"approve", "reject", "before_sign", "after_sign", "complete_handling"}:
        raise TaskActionInvalid("不支持的任务动作")
    if not isinstance(reason, str) or len(reason) > 500 or action in {"reject", "before_sign", "after_sign"} and not reason.strip():
        raise TaskActionInvalid("请填写操作原因，最多 500 个字符")
    normalized_users = user_ids or []
    fingerprint = _digest(
        {
            "task_id": str(task_id),
            "action": action,
            "user_ids": normalized_users,
            "reason": reason,
        }
    )
    idempotency_key = f"itsm:task-action:{domain}:{actor_user_id}:{request_id}"

    with transaction.atomic():
        existing = Command.objects.select_for_update().filter(idempotency_key=idempotency_key).first()
        if existing is not None:
            if existing.fingerprint != fingerprint:
                raise TaskActionConflict("同一 request_id 已提交不同任务动作")
            return TaskActionResult(existing, False, existing.command_type == Command.Type.PLAN_AFTER_SIGN)

        task = (
            TaskProjection.objects.select_for_update()
            .select_related("ticket")
            .filter(
                pk=task_id,
                domain=domain,
                team_id=team_id,
                assignee_user_id=actor_user_id,
                status=TaskProjection.Status.PENDING,
            )
            .first()
        )
        if task is None:
            raise TaskProjection.DoesNotExist
        if task.ticket.commands.filter(status__in=ACTIVE_COMMAND_STATUSES).exists():
            raise TaskActionConflict("该工单已有操作正在提交，请稍后刷新")

        is_approval = task.task_type == TaskProjection.Type.APPROVAL
        if action in {"approve", "reject", "before_sign", "after_sign"} and not is_approval:
            raise TaskActionInvalid("该任务不是审批任务")
        if action == "complete_handling" and task.task_type != TaskProjection.Type.HANDLING:
            raise TaskActionInvalid("该任务不是处理任务")
        if action in {"before_sign", "after_sign"} and task.sign_parent_key:
            raise TaskActionInvalid("加签产生的任务不允许继续递归加签")

        if action in {"before_sign", "after_sign"}:
            allowed = task.allow_before_sign if action == "before_sign" else task.allow_after_sign
            if not allowed:
                raise TaskActionInvalid("当前审批节点未开放此加签方式")
            normalized_users = _validate_sign_users(
                normalized_users,
                actor_user_id=actor_user_id,
                domain=domain,
                team_id=team_id,
            )

        if action == "after_sign":
            if SignPlan.objects.filter(ticket=task.ticket, task_logical_key=task.logical_key).exists():
                raise TaskActionConflict("当前审批已有后加签计划，不能无提示覆盖")
            SignPlan.objects.create(
                ticket=task.ticket,
                task_logical_key=task.logical_key,
                user_ids=normalized_users,
                created_by_user_id=actor_user_id,
                created_by_username=actor_username,
                created_by_domain=domain,
                reason=reason,
            )
            command = Command.objects.create(
                ticket=task.ticket,
                service_version=task.ticket.service_version,
                command_type=Command.Type.PLAN_AFTER_SIGN,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
                target_id=task.engine_task_id,
                request_payload={
                    "action": action,
                    "actor_user_id": actor_user_id,
                    "user_ids": normalized_users,
                    "reason": reason,
                },
                status=Command.Status.SUCCEEDED,
                completed_at=timezone.now(),
                result={"planned": True},
            )
            AuditEvent.objects.create(
                ticket=task.ticket,
                command=command,
                actor_user_id=actor_user_id,
                actor_username=actor_username,
                actor_domain=domain,
                action="AFTER_SIGN_PLANNED",
                reason=reason,
                detail={"user_ids": normalized_users, "task_id": str(task.id)},
            )
            return TaskActionResult(command, True, True)

        post_plan = SignPlan.objects.filter(ticket=task.ticket, task_logical_key=task.logical_key, applied=False).first()
        command = Command.objects.create(
            ticket=task.ticket,
            service_version=task.ticket.service_version,
            command_type=Command.Type.COMPLETE_TASK,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            target_id=task.engine_task_id,
            request_payload={},
        )
        receipt = f"{command.id}:{fingerprint}"
        receipt_variable = f"itsmReceipt_{command.id.hex}"
        if action == "before_sign":
            variables = [
                variable("intent", "before"),
                variable("vote", False),
                variable("hasPost", False),
                variable("postUsers", []),
                variable("signUsers", [str(item) for item in normalized_users]),
                variable(receipt_variable, receipt),
            ]
        elif action in {"approve", "reject"}:
            post_users = post_plan.user_ids if action == "approve" and post_plan else []
            variables = [
                variable("intent", "complete"),
                variable("vote", action == "approve"),
                variable("hasPost", bool(post_users)),
                variable("postUsers", [str(item) for item in post_users]),
                variable("signUsers", []),
                variable(receipt_variable, receipt),
            ]
            if post_plan and post_users:
                post_plan.applied = True
                post_plan.save(update_fields=("applied", "updated_at"))
        else:
            variables = [variable(receipt_variable, receipt)]

        command.receipt_key = receipt
        command.request_payload = {
            "action": action,
            "task_projection_id": str(task.id),
            "actor_user_id": actor_user_id,
            "reason": reason,
            "receipt_variable": receipt_variable,
            "variables": variables,
        }
        command.save(update_fields=("receipt_key", "request_payload", "updated_at"))
        task.status = TaskProjection.Status.SUBMITTING
        task.save(update_fields=("status", "updated_at"))
        AuditEvent.objects.create(
            ticket=task.ticket,
            command=command,
            actor_user_id=actor_user_id,
            actor_username=actor_username,
            actor_domain=domain,
            action=f"{action.upper()}_REQUESTED",
            reason=reason,
            detail={"task_id": str(task.id), "user_ids": normalized_users},
        )
        return TaskActionResult(command, True, False)
