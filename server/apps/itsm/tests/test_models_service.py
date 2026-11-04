import pytest
from django.db import IntegrityError, transaction

from apps.itsm.models import Command, Service, ServiceVersion, Ticket


def service_defaults():
    return {
        "name": "数据库申请",
        "description": "申请业务数据库",
        "domain": "example.com",
        "team_id": 7,
        "created_by": "admin",
        "updated_by": "admin",
        "updated_by_domain": "example.com",
        "form_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string", "title": "摘要", "maxLength": 120}},
            "required": ["summary"],
            "additionalProperties": False,
        },
        "workflow_config": {
            "schemaVersion": 1,
            "stages": [
                {
                    "key": "manager",
                    "name": "主管审批",
                    "mode": "serial",
                    "approverIds": [11],
                    "allowBeforeSign": True,
                    "allowAfterSign": True,
                }
            ],
            "handlerIds": [21],
        },
    }


@pytest.mark.django_db
def test_service_name_is_unique_inside_domain_and_team():
    Service.objects.create(**service_defaults())

    with pytest.raises(IntegrityError), transaction.atomic():
        Service.objects.create(**service_defaults())

    other_team = service_defaults()
    other_team["team_id"] = 8
    Service.objects.create(**other_team)


@pytest.mark.django_db
def test_service_version_is_unique_and_keeps_frozen_contract():
    service = Service.objects.create(**service_defaults())
    version = ServiceVersion.objects.create(
        service=service,
        version=1,
        source_revision=0,
        form_schema=service.form_schema,
        workflow_config=service.workflow_config,
        content_hash="a" * 64,
        created_by="admin",
        domain="example.com",
    )

    assert version.publish_status == ServiceVersion.PublishStatus.PENDING
    assert version.form_schema == service.form_schema

    with pytest.raises(IntegrityError), transaction.atomic():
        ServiceVersion.objects.create(
            service=service,
            version=1,
            source_revision=1,
            form_schema=service.form_schema,
            workflow_config=service.workflow_config,
            content_hash="b" * 64,
            created_by="admin",
            domain="example.com",
        )


@pytest.mark.django_db
def test_ticket_request_key_is_idempotent_per_requester_and_domain():
    service = Service.objects.create(**service_defaults())
    version = ServiceVersion.objects.create(
        service=service,
        version=1,
        source_revision=0,
        form_schema=service.form_schema,
        workflow_config=service.workflow_config,
        content_hash="a" * 64,
        created_by="admin",
        domain="example.com",
    )
    payload = {
        "number": "ITSM-20261103-000001",
        "service": service,
        "service_version": version,
        "domain": "example.com",
        "team_id": 7,
        "requester_user_id": 101,
        "requester_username": "alice",
        "request_key": "request-001",
        "request_fingerprint": "b" * 64,
        "form_data": {"summary": "需要数据库"},
    }
    Ticket.objects.create(**payload)

    with pytest.raises(IntegrityError), transaction.atomic():
        Ticket.objects.create(**{**payload, "number": "ITSM-20261103-000002"})

    Ticket.objects.create(
        **{
            **payload,
            "number": "ITSM-20261103-000003",
            "requester_user_id": 102,
            "requester_username": "bob",
        }
    )


@pytest.mark.django_db
def test_command_starts_pending_without_a_lease():
    service = Service.objects.create(**service_defaults())
    version = ServiceVersion.objects.create(
        service=service,
        version=1,
        source_revision=0,
        form_schema=service.form_schema,
        workflow_config=service.workflow_config,
        content_hash="a" * 64,
        created_by="admin",
        domain="example.com",
    )
    command = Command.objects.create(
        service_version=version,
        command_type=Command.Type.DEPLOY_VERSION,
        idempotency_key="deploy:1:1",
        fingerprint="c" * 64,
        request_payload={"version_id": version.id},
    )

    assert command.status == Command.Status.PENDING
    assert command.attempts == 0
    assert command.lease_token is None
    assert command.lease_expires_at is None
