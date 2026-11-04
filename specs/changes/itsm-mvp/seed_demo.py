"""Seed and deploy a repeatable local ITSM demonstration."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402

from apps.itsm.models import Command, Service, Ticket  # noqa: E402
from apps.itsm.services.dispatcher import dispatch_command  # noqa: E402
from apps.itsm.services.flowable import FlowableClient  # noqa: E402
from apps.itsm.services.publication import publish_service  # noqa: E402
from apps.itsm.services.tickets import submit_ticket  # noqa: E402


DOMAIN = "domain.com"
TEAM_ID = 7
USERS = [
    (101, "demo-admin"),
    (102, "manager-b"),
    (201, "security-a"),
    (202, "security-b"),
    (301, "handler"),
]
FORM_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "title": "申请摘要", "maxLength": 120, "x-widget": "input"},
        "description": {"type": "string", "title": "申请说明", "maxLength": 2000, "x-widget": "textarea"},
        "environment": {
            "type": "string",
            "title": "目标环境",
            "enum": ["测试", "预发布", "生产"],
            "x-widget": "select",
        },
    },
    "required": ["summary", "environment"],
    "additionalProperties": False,
}
WORKFLOW = {
    "schemaVersion": 1,
    "stages": [
        {
            "key": "manager",
            "name": "主管审批",
            "mode": "serial",
            "approverIds": [101, 102],
            "allowBeforeSign": True,
            "allowAfterSign": True,
        },
        {
            "key": "security",
            "name": "安全会签",
            "mode": "parallel",
            "approverIds": [201, 202],
            "allowBeforeSign": False,
            "allowAfterSign": False,
        },
    ],
    "handlerIds": [301],
}


def seed_users():
    user_model = get_user_model()
    for user_id, username in USERS:
        user, _ = user_model.objects.update_or_create(
            id=user_id,
            defaults={
                "username": username,
                "domain": DOMAIN,
                "group_list": [TEAM_ID],
                "roles": ["itsm--admin"] if user_id == 101 else [],
                "is_active": True,
                "is_superuser": user_id == 101,
                "is_staff": user_id == 101,
                "locale": "zh-Hans",
            },
        )
        user.set_unusable_password()
        user.save(update_fields=("password",))


def seed_service(client):
    service, _ = Service.objects.update_or_create(
        domain=DOMAIN,
        team_id=TEAM_ID,
        name="数据库资源申请",
        defaults={
            "description": "申请生产数据库、账号与容量配额",
            "form_schema": FORM_SCHEMA,
            "workflow_config": WORKFLOW,
            "draft_revision": 1,
            "created_by": "demo-admin",
            "updated_by": "demo-admin",
            "updated_by_domain": DOMAIN,
        },
    )
    if service.current_version == 0:
        _version, command = publish_service(
            service.id,
            username="demo-admin",
            domain=DOMAIN,
            team_id=TEAM_ID,
        )
        dispatch_command(command.id, client=client)
        service.refresh_from_db()
    return service


def seed_ticket(service, client):
    ticket, created = submit_ticket(
        service_id=service.id,
        form_data={
            "summary": "订单数据库扩容至 500 GB",
            "description": "用于双十一容量准备，请审批。",
            "environment": "生产",
        },
        request_key="demo-initial-ticket-v1",
        user_id=101,
        username="demo-admin",
        domain=DOMAIN,
        team_id=TEAM_ID,
    )
    if created:
        command = ticket.commands.get(command_type=Command.Type.START_TICKET)
        dispatch_command(command.id, client=client)
    return ticket


seed_users()
flowable = FlowableClient()
try:
    demo_service = seed_service(flowable)
    demo_ticket = seed_ticket(demo_service, flowable)
finally:
    flowable.close()

print(
    f"ITSM demo seeded: service={demo_service.id} ticket={demo_ticket.number} "
    f"status={Ticket.objects.get(pk=demo_ticket.pk).status}"
)
