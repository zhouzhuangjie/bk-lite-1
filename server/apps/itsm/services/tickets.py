from __future__ import annotations

import hashlib
import json
import re
import uuid

from django.db import transaction
from django.utils import timezone

from apps.itsm.models import AuditEvent, Command, Service, ServiceVersion, Ticket
from apps.itsm.services.flowable import variable
from apps.itsm.services.validation import ITSMValidationError, validate_submission

REQUEST_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class TicketConflict(ValueError):
    pass


def _digest(value: dict) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _ticket_number(ticket_id: uuid.UUID) -> str:
    return f"ITSM-{timezone.localdate():%Y%m%d}-{ticket_id.hex[:8].upper()}"


def submit_ticket(
    *,
    service_id: int,
    form_data: dict,
    request_key: str,
    user_id: int,
    username: str,
    domain: str,
    team_id: int,
) -> tuple[Ticket, bool]:
    if not isinstance(request_key, str) or not REQUEST_KEY_PATTERN.fullmatch(request_key):
        raise ITSMValidationError("request_key 格式非法")
    request_fingerprint = _digest({"service_id": service_id, "form_data": form_data})

    with transaction.atomic():
        existing = (
            Ticket.objects.select_for_update()
            .filter(
                domain=domain,
                requester_user_id=user_id,
                request_key=request_key,
            )
            .first()
        )
        if existing is not None:
            if existing.request_fingerprint != request_fingerprint:
                raise TicketConflict("同一 request_key 已提交不同内容")
            return existing, False

        service = (
            Service.objects.select_for_update()
            .filter(
                pk=service_id,
                domain=domain,
                team_id=team_id,
                status=Service.Status.PUBLISHED,
                deleted_at__isnull=True,
            )
            .first()
        )
        if service is None or service.current_version <= 0:
            raise ITSMValidationError("服务不存在、未发布或已停用")
        version = ServiceVersion.objects.filter(
            service=service,
            version=service.current_version,
            publish_status=ServiceVersion.PublishStatus.READY,
        ).first()
        if version is None or not version.engine_process_definition_id:
            raise ITSMValidationError("服务版本尚未准备完成")
        validate_submission(version.form_schema, form_data)

        ticket_id = uuid.uuid4()
        ticket = Ticket.objects.create(
            id=ticket_id,
            number=_ticket_number(ticket_id),
            service=service,
            service_version=version,
            domain=domain,
            team_id=team_id,
            requester_user_id=user_id,
            requester_username=username,
            request_key=request_key,
            request_fingerprint=request_fingerprint,
            form_data=form_data,
        )
        variables = [variable("approved", True), variable("handlerId", str(version.workflow_config["handlerIds"][0]))]
        for stage in version.workflow_config["stages"]:
            variables.append(variable(f"approval_{stage['key']}", [str(item) for item in stage["approverIds"]]))
        command = Command.objects.create(
            ticket=ticket,
            service_version=version,
            command_type=Command.Type.START_TICKET,
            idempotency_key=f"itsm:ticket:{ticket.id}:start",
            fingerprint=request_fingerprint,
            request_payload={
                "process_definition_id": version.engine_process_definition_id,
                "business_key": str(ticket.id),
                "variables": variables,
            },
            receipt_key=f"itsm-start-{ticket.id}",
        )
        AuditEvent.objects.create(
            ticket=ticket,
            command=command,
            actor_user_id=user_id,
            actor_username=username,
            actor_domain=domain,
            action="SUBMIT_REQUESTED",
            to_status=Ticket.Status.SUBMITTING,
        )
        return ticket, True
