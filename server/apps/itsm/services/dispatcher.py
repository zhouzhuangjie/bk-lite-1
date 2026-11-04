from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.logger import itsm_logger as logger
from apps.core.logger import safe_exception_info
from apps.itsm.models import AuditEvent, Command, Service, ServiceVersion, TaskProjection, Ticket
from apps.itsm.services.bpmn import build_deployment_archive
from apps.itsm.services.flowable import FlowableClient, FlowableConnectionUnavailable, FlowableRejected, FlowableUnavailable

DEFAULT_LEASE_SECONDS = 300
MAX_BATCH_SIZE = 50


@dataclass(frozen=True)
class ClaimedCommand:
    command_id: uuid.UUID
    lease_token: uuid.UUID
    previously_sent: bool


def _apply_terminal_failure_side_effects(command: Command, error_type: str) -> None:
    if command.command_type == Command.Type.COMPLETE_TASK:
        payload = command.request_payload if isinstance(command.request_payload, dict) else {}
        task_projection_id = payload.get("task_projection_id")
        terminal_projection_errors = {"RECEIPT_CONFLICT", "TASK_ENDED_WITHOUT_RECEIPT"}
        TaskProjection.objects.filter(
            pk=task_projection_id,
            status=TaskProjection.Status.SUBMITTING,
        ).update(status=(TaskProjection.Status.CANCELLED if error_type in terminal_projection_errors else TaskProjection.Status.PENDING))
    elif command.command_type == Command.Type.DEPLOY_VERSION and command.service_version_id:
        ServiceVersion.objects.filter(pk=command.service_version_id).update(
            publish_status=ServiceVersion.PublishStatus.FAILED,
            publish_error=error_type,
        )


def due_command_ids(*, now=None, batch_size: int = MAX_BATCH_SIZE) -> list[uuid.UUID]:
    current = now or timezone.now()
    limit = max(1, min(int(batch_size), MAX_BATCH_SIZE))
    pending = Q(status=Command.Status.PENDING)
    retry = Q(status=Command.Status.RETRY) & (Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=current))
    expired = Q(status=Command.Status.DELIVERING) & (Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=current))
    reconcile = Q(status=Command.Status.UNCERTAIN) & Q(next_attempt_at__lte=current)
    return list(Command.objects.filter(pending | retry | expired | reconcile).order_by("created_at", "id").values_list("id", flat=True)[:limit])


def claim_command(command_id, *, now=None, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> ClaimedCommand | None:
    current = now or timezone.now()
    with transaction.atomic():
        command = Command.objects.select_for_update().filter(pk=command_id).first()
        if command is None or command.status in {Command.Status.SUCCEEDED, Command.Status.FAILED}:
            return None
        if command.status == Command.Status.DELIVERING and command.lease_expires_at and command.lease_expires_at > current:
            return None
        if command.status in {Command.Status.RETRY, Command.Status.UNCERTAIN} and command.next_attempt_at and command.next_attempt_at > current:
            return None
        if command.attempts >= command.max_attempts:
            command.status = Command.Status.FAILED
            command.last_error = "MAX_ATTEMPTS_EXCEEDED"
            command.lease_token = None
            command.lease_expires_at = None
            command.save(update_fields=("status", "last_error", "lease_token", "lease_expires_at", "updated_at"))
            _apply_terminal_failure_side_effects(command, command.last_error)
            return None

        token = uuid.uuid4()
        previously_sent = command.sent_at is not None
        command.status = Command.Status.DELIVERING
        command.attempts += 1
        command.lease_token = token
        command.lease_expires_at = current + timedelta(seconds=max(1, lease_seconds))
        if command.sent_at is None:
            command.sent_at = current
        command.save(update_fields=("status", "attempts", "lease_token", "lease_expires_at", "sent_at", "updated_at"))
        return ClaimedCommand(command_id=command.id, lease_token=token, previously_sent=previously_sent)


def finalize_command_success(command_id, lease_token: uuid.UUID, result: dict[str, Any]) -> bool:
    now = timezone.now()
    updated = Command.objects.filter(
        pk=command_id,
        lease_token=lease_token,
        status=Command.Status.DELIVERING,
    ).update(
        status=Command.Status.SUCCEEDED,
        result=result,
        last_error="",
        completed_at=now,
        next_attempt_at=None,
        lease_token=None,
        lease_expires_at=None,
        updated_at=now,
    )
    return updated == 1


def _retry_after(attempts: int) -> timedelta:
    return timedelta(seconds=min(300, 5 * (2 ** min(max(attempts - 1, 0), 6))))


def _mark_retry(command_id, lease_token: uuid.UUID, *, error_type: str, definite_connection_failure: bool) -> bool:
    with transaction.atomic():
        command = (
            Command.objects.select_for_update()
            .filter(
                pk=command_id,
                lease_token=lease_token,
                status=Command.Status.DELIVERING,
            )
            .first()
        )
        if command is None:
            return False
        command.status = Command.Status.RETRY if definite_connection_failure else Command.Status.UNCERTAIN
        command.next_attempt_at = timezone.now() + _retry_after(command.attempts)
        command.last_error = error_type
        command.lease_token = None
        command.lease_expires_at = None
        if definite_connection_failure:
            command.sent_at = None
            if command.command_type == Command.Type.DEPLOY_VERSION and command.service_version_id:
                ServiceVersion.objects.filter(
                    pk=command.service_version_id,
                    publish_status=ServiceVersion.PublishStatus.DEPLOYING,
                ).update(publish_status=ServiceVersion.PublishStatus.PENDING)
        command.save(
            update_fields=(
                "status",
                "next_attempt_at",
                "last_error",
                "lease_token",
                "lease_expires_at",
                "sent_at",
                "updated_at",
            )
        )
        return True


def _mark_failed(command_id, lease_token: uuid.UUID, *, error_type: str) -> bool:
    with transaction.atomic():
        command = (
            Command.objects.select_for_update()
            .filter(
                pk=command_id,
                lease_token=lease_token,
                status=Command.Status.DELIVERING,
            )
            .first()
        )
        if command is None:
            return False
        command.status = Command.Status.FAILED
        command.last_error = error_type
        command.completed_at = timezone.now()
        command.next_attempt_at = None
        command.lease_token = None
        command.lease_expires_at = None
        command.save(
            update_fields=(
                "status",
                "last_error",
                "completed_at",
                "next_attempt_at",
                "lease_token",
                "lease_expires_at",
                "updated_at",
            )
        )
        _apply_terminal_failure_side_effects(command, error_type)
        return True


def _finalize_deployment(command_id, lease_token: uuid.UUID, result: dict[str, str]) -> bool:
    with transaction.atomic():
        command = (
            Command.objects.select_for_update()
            .select_related("service_version__service")
            .filter(
                pk=command_id,
                lease_token=lease_token,
                status=Command.Status.DELIVERING,
            )
            .first()
        )
        if command is None or command.service_version is None:
            return False
        version = command.service_version
        version.publish_status = ServiceVersion.PublishStatus.READY
        version.engine_deployment_id = result["deployment_id"]
        version.engine_process_definition_id = result["process_definition_id"]
        version.publish_error = ""
        version.save(
            update_fields=(
                "publish_status",
                "engine_deployment_id",
                "engine_process_definition_id",
                "publish_error",
                "updated_at",
            )
        )
        service = version.service
        if version.version >= service.current_version:
            service.current_version = version.version
            service.status = Service.Status.PUBLISHED
            service.save(update_fields=("current_version", "status", "updated_at"))
        return finalize_command_success(command.id, lease_token, result)


def _dispatch_deployment(claimed: ClaimedCommand, client: FlowableClient) -> None:
    command = Command.objects.select_related("service_version__service").get(pk=claimed.command_id)
    version = command.service_version
    if version is None:
        _mark_failed(command.id, claimed.lease_token, error_type="MISSING_SERVICE_VERSION")
        return
    payload = command.request_payload if isinstance(command.request_payload, dict) else {}
    process_key = str(payload.get("process_key") or "")
    deployment_name = str(payload.get("deployment_name") or "")
    if not process_key or not deployment_name:
        _mark_failed(command.id, claimed.lease_token, error_type="INVALID_DEPLOYMENT_COMMAND")
        return

    ServiceVersion.objects.filter(pk=version.pk, publish_status=ServiceVersion.PublishStatus.PENDING).update(
        publish_status=ServiceVersion.PublishStatus.DEPLOYING
    )
    if claimed.previously_sent:
        reconciled = client.find_deployment(deployment_name, process_key=process_key)
        if reconciled is None:
            _mark_retry(command.id, claimed.lease_token, error_type="DEPLOYMENT_OUTCOME_UNKNOWN", definite_connection_failure=False)
            return
        _finalize_deployment(command.id, claimed.lease_token, reconciled)
        return

    archive = build_deployment_archive(
        process_key=process_key,
        process_name=f"{version.service.name} v{version.version}",
        workflow_config=version.workflow_config,
    )
    result = client.deploy_archive(deployment_name, archive, process_key=process_key)
    _finalize_deployment(command.id, claimed.lease_token, result)


def _finalize_start(command_id, lease_token: uuid.UUID, process_instance_id: str) -> Ticket | None:
    conflict = False
    with transaction.atomic():
        command = (
            Command.objects.select_for_update()
            .select_related("ticket")
            .filter(
                pk=command_id,
                lease_token=lease_token,
                status=Command.Status.DELIVERING,
            )
            .first()
        )
        if command is None or command.ticket is None:
            return None
        ticket = command.ticket
        if ticket.engine_process_instance_id and ticket.engine_process_instance_id != process_instance_id:
            conflict = True
        else:
            ticket.engine_process_instance_id = process_instance_id
            ticket.status = Ticket.Status.APPROVING
            ticket.save(update_fields=("engine_process_instance_id", "status", "updated_at"))
            AuditEvent.objects.get_or_create(
                ticket=ticket,
                command=command,
                action="PROCESS_STARTED",
                defaults={
                    "actor_domain": ticket.domain,
                    "from_status": Ticket.Status.SUBMITTING,
                    "to_status": Ticket.Status.APPROVING,
                },
            )
            if not finalize_command_success(command.id, lease_token, {"process_instance_id": process_instance_id}):
                return None
            return ticket
    if conflict:
        _mark_failed(command_id, lease_token, error_type="PROCESS_INSTANCE_CONFLICT")
    return None


def sync_ticket_tasks(ticket_id, client: FlowableClient) -> None:
    ticket = Ticket.objects.get(pk=ticket_id)
    if not ticket.engine_process_instance_id:
        return
    active_tasks = client.active_tasks(ticket.engine_process_instance_id)
    active_ids = {item["id"] for item in active_tasks if item.get("id")}
    process_result = client.process_result(ticket.engine_process_instance_id) if not active_tasks else "running"
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket_id)
        TaskProjection.objects.filter(
            ticket=ticket,
            status__in=(TaskProjection.Status.PENDING, TaskProjection.Status.SUBMITTING),
        ).exclude(
            engine_task_id__in=active_ids
        ).update(status=TaskProjection.Status.CANCELLED)
        for item in active_tasks:
            try:
                assignee_user_id = int(item["assignee"])
            except (TypeError, ValueError):
                logger.warning(
                    "event=itsm_task_projection_skipped ticket_id=%s error_type=INVALID_ASSIGNEE",
                    ticket.id,
                )
                continue
            task_type = TaskProjection.Type.HANDLING if item["definition_key"] == "handle" else TaskProjection.Type.APPROVAL
            TaskProjection.objects.update_or_create(
                engine_task_id=item["id"],
                defaults={
                    "ticket": ticket,
                    "logical_key": f"{item['process_instance_id']}:{item['definition_key']}",
                    "task_type": task_type,
                    "title": item["name"][:120] or ("处理工单" if task_type == TaskProjection.Type.HANDLING else "审批工单"),
                    "domain": ticket.domain,
                    "team_id": ticket.team_id,
                    "assignee_user_id": assignee_user_id,
                    "status": TaskProjection.Status.PENDING,
                    "stage_key": item["stage_key"][:64],
                    "allow_before_sign": item["allow_before_sign"],
                    "allow_after_sign": item["allow_after_sign"],
                    "sign_parent_key": "" if item["depth"] == 0 else item["process_instance_id"],
                },
            )
        if any(item["definition_key"] == "handle" for item in active_tasks):
            ticket.status = Ticket.Status.PROCESSING
        elif active_tasks:
            ticket.status = Ticket.Status.APPROVING
        else:
            if process_result == "rejected":
                ticket.status = Ticket.Status.REJECTED
            elif process_result == "completed":
                ticket.status = Ticket.Status.WAITING_CONFIRMATION
                ticket.resolved_at = timezone.now()
        ticket.save(update_fields=("status", "resolved_at", "updated_at"))


def _finalize_task_completion(command_id, lease_token: uuid.UUID) -> Ticket | None:
    with transaction.atomic():
        command = (
            Command.objects.select_for_update()
            .select_related("ticket")
            .filter(
                pk=command_id,
                lease_token=lease_token,
                status=Command.Status.DELIVERING,
            )
            .first()
        )
        if command is None or command.ticket is None:
            return None
        payload = command.request_payload if isinstance(command.request_payload, dict) else {}
        task_projection_id = payload.get("task_projection_id")
        task = (
            TaskProjection.objects.select_for_update()
            .filter(
                pk=task_projection_id,
                ticket=command.ticket,
                engine_task_id=command.target_id,
                status=TaskProjection.Status.SUBMITTING,
            )
            .first()
        )
        if task is None:
            return None

        now = timezone.now()
        task.status = TaskProjection.Status.COMPLETED
        task.completed_at = now
        task.save(update_fields=("status", "completed_at", "updated_at"))
        AuditEvent.objects.get_or_create(
            ticket=command.ticket,
            command=command,
            action=f"{str(payload.get('action') or 'TASK').upper()}_APPLIED",
            defaults={
                "actor_user_id": payload.get("actor_user_id"),
                "actor_domain": command.ticket.domain,
                "reason": str(payload.get("reason") or "")[:500],
                "detail": {"task_id": str(task.id)},
            },
        )
        if not finalize_command_success(
            command.id,
            lease_token,
            {"engine_task_id": command.target_id, "receipt": command.receipt_key},
        ):
            return None
        return command.ticket


def _dispatch_task_completion(claimed: ClaimedCommand, client: FlowableClient) -> None:
    command = Command.objects.select_related("ticket").get(pk=claimed.command_id)
    if command.ticket is None:
        _mark_failed(command.id, claimed.lease_token, error_type="MISSING_TICKET")
        return
    payload = command.request_payload if isinstance(command.request_payload, dict) else {}
    variables = payload.get("variables")
    task_projection_id = payload.get("task_projection_id")
    receipt_variable = str(payload.get("receipt_variable") or "")
    if (
        not command.target_id
        or not command.receipt_key
        or not receipt_variable.startswith("itsmReceipt_")
        or not isinstance(variables, list)
        or not task_projection_id
    ):
        _mark_failed(command.id, claimed.lease_token, error_type="INVALID_TASK_COMMAND")
        return
    if not TaskProjection.objects.filter(
        pk=task_projection_id,
        ticket=command.ticket,
        engine_task_id=command.target_id,
        status=TaskProjection.Status.SUBMITTING,
    ).exists():
        _mark_failed(command.id, claimed.lease_token, error_type="INVALID_TASK_PROJECTION")
        return

    if claimed.previously_sent:
        receipt = client.historic_receipt(receipt_variable)
        if receipt:
            if receipt != command.receipt_key:
                _mark_failed(command.id, claimed.lease_token, error_type="RECEIPT_CONFLICT")
                return
        elif not client.task_exists(command.target_id):
            _mark_failed(command.id, claimed.lease_token, error_type="TASK_ENDED_WITHOUT_RECEIPT")
            return
        else:
            client.complete_task(command.target_id, variables=variables)
    else:
        client.complete_task(command.target_id, variables=variables)

    ticket = _finalize_task_completion(command.id, claimed.lease_token)
    if ticket is not None:
        try:
            sync_ticket_tasks(ticket.id, client)
        except FlowableUnavailable as error:
            logger.warning(
                "event=itsm_task_projection_sync_deferred ticket_id=%s error_type=%s",
                ticket.id,
                type(error).__name__,
            )


def _dispatch_start(claimed: ClaimedCommand, client: FlowableClient) -> None:
    command = Command.objects.select_related("ticket").get(pk=claimed.command_id)
    ticket = command.ticket
    if ticket is None:
        _mark_failed(command.id, claimed.lease_token, error_type="MISSING_TICKET")
        return
    payload = command.request_payload if isinstance(command.request_payload, dict) else {}
    definition_id = str(payload.get("process_definition_id") or "")
    business_key = str(payload.get("business_key") or "")
    variables = payload.get("variables")
    if not definition_id or business_key != str(ticket.id) or not isinstance(variables, list):
        _mark_failed(command.id, claimed.lease_token, error_type="INVALID_START_COMMAND")
        return

    if claimed.previously_sent:
        matches = client.historic_processes(business_key=business_key)
        if len(matches) == 1 and matches[0].get("id"):
            started = _finalize_start(command.id, claimed.lease_token, str(matches[0]["id"]))
        elif len(matches) > 1:
            _mark_failed(command.id, claimed.lease_token, error_type="DUPLICATE_PROCESS_INSTANCES")
            return
        else:
            _mark_retry(command.id, claimed.lease_token, error_type="START_OUTCOME_UNKNOWN", definite_connection_failure=False)
            return
    else:
        result = client.start_process(definition_id, business_key=business_key, variables=variables)
        process_instance_id = str(result.get("id") or "")
        if not process_instance_id:
            raise FlowableUnavailable("Flowable 未返回 process instance id")
        started = _finalize_start(command.id, claimed.lease_token, process_instance_id)

    if started is not None:
        try:
            sync_ticket_tasks(started.id, client)
        except FlowableUnavailable as error:
            logger.warning(
                "event=itsm_task_projection_sync_deferred ticket_id=%s error_type=%s",
                started.id,
                type(error).__name__,
            )


def dispatch_command(command_id, *, client: FlowableClient | None = None) -> None:
    claimed = claim_command(command_id)
    if claimed is None:
        return
    own_client = client is None
    active_client = client or FlowableClient()
    try:
        command = Command.objects.only("command_type").get(pk=claimed.command_id)
        if command.command_type == Command.Type.DEPLOY_VERSION:
            _dispatch_deployment(claimed, active_client)
        elif command.command_type == Command.Type.START_TICKET:
            _dispatch_start(claimed, active_client)
        elif command.command_type == Command.Type.COMPLETE_TASK:
            _dispatch_task_completion(claimed, active_client)
        else:
            _mark_failed(command.id, claimed.lease_token, error_type="UNSUPPORTED_COMMAND_TYPE")
    except FlowableConnectionUnavailable as error:
        _mark_retry(claimed.command_id, claimed.lease_token, error_type=type(error).__name__, definite_connection_failure=True)
    except FlowableRejected as error:
        _mark_failed(claimed.command_id, claimed.lease_token, error_type=type(error).__name__)
    except FlowableUnavailable as error:
        _mark_retry(claimed.command_id, claimed.lease_token, error_type=type(error).__name__, definite_connection_failure=False)
    except Exception as error:
        _mark_retry(claimed.command_id, claimed.lease_token, error_type=type(error).__name__, definite_connection_failure=False)
        logger.error(
            "event=itsm_command_dispatch_failed command_id=%s failed_stage=dispatch error_type=%s",
            claimed.command_id,
            type(error).__name__,
            exc_info=safe_exception_info(error),
        )
    finally:
        if own_client:
            active_client.close()
