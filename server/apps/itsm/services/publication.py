from __future__ import annotations

import hashlib
import json

from django.contrib.auth import get_user_model
from django.db import transaction

from apps.core.utils.user_group import normalize_user_group_ids
from apps.itsm.models import Command, Service, ServiceVersion
from apps.itsm.services.validation import ITSMValidationError, validate_form_schema, validate_workflow_config


def _content_hash(form_schema: dict, workflow_config: dict) -> str:
    content = json.dumps(
        {"form_schema": form_schema, "workflow_config": workflow_config},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _validate_workflow_principals(workflow_config: dict, *, domain: str, team_id: int) -> None:
    principal_ids = set(workflow_config["handlerIds"])
    for stage in workflow_config["stages"]:
        principal_ids.update(stage["approverIds"])
    users = (
        get_user_model()
        .objects.select_for_update()
        .filter(
            id__in=principal_ids,
            domain=domain,
            is_active=True,
        )
        .only("id", "group_list")
    )
    valid_ids = {user.id for user in users if team_id in set(normalize_user_group_ids(user.group_list))}
    if valid_ids != principal_ids:
        raise ITSMValidationError("流程中的审批人或处理人已失效，或不属于当前组织")


def publish_service(service_id: int, *, username: str, domain: str, team_id: int) -> tuple[ServiceVersion, Command]:
    with transaction.atomic():
        service = Service.objects.select_for_update().get(
            pk=service_id,
            domain=domain,
            team_id=team_id,
            deleted_at__isnull=True,
        )
        validate_form_schema(service.form_schema)
        validate_workflow_config(service.workflow_config)
        _validate_workflow_principals(service.workflow_config, domain=domain, team_id=team_id)

        existing = service.versions.filter(source_revision=service.draft_revision).first()
        if existing is not None:
            command = Command.objects.get(service_version=existing, command_type=Command.Type.DEPLOY_VERSION)
            return existing, command

        version_number = service.versions.count() + 1
        version = ServiceVersion.objects.create(
            service=service,
            version=version_number,
            source_revision=service.draft_revision,
            form_schema=service.form_schema,
            workflow_config=service.workflow_config,
            content_hash=_content_hash(service.form_schema, service.workflow_config),
            created_by=username,
            domain=domain,
        )
        process_key = f"itsm_service_{service.id}_v{version_number}"
        command = Command.objects.create(
            service_version=version,
            command_type=Command.Type.DEPLOY_VERSION,
            idempotency_key=f"itsm:service:{service.id}:revision:{service.draft_revision}:deploy",
            fingerprint=version.content_hash,
            request_payload={
                "service_version_id": version.id,
                "deployment_name": process_key,
                "process_key": process_key,
            },
            receipt_key=f"itsm-deploy-{version.id}",
        )
        service.last_published_revision = service.draft_revision
        service.updated_by = username
        service.updated_by_domain = domain
        service.save(update_fields=("last_published_revision", "updated_by", "updated_by_domain", "updated_at"))
        return version, command
