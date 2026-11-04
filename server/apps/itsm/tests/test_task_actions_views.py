import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.itsm.models import Command, Service, ServiceVersion, SignPlan, TaskProjection, Ticket
from apps.itsm.views import TaskViewSet


@pytest.fixture
def task_case(db):
    actor = get_user_model().objects.create(
        username="approver",
        domain="example.com",
        group_list=[{"id": 7, "name": "研发部"}],
    )
    target = get_user_model().objects.create(
        username="signer",
        domain="example.com",
        group_list=[{"id": 7, "name": "研发部"}],
    )
    outsider = get_user_model().objects.create(
        username="outsider",
        domain="example.com",
        group_list=[{"id": 7, "name": "研发部"}],
    )
    for user in (actor, target, outsider):
        user.permission = {"itsm": {"todo-View", "todo-Act"}}
    schema = {
        "type": "object",
        "properties": {"summary": {"type": "string", "title": "摘要", "maxLength": 120}},
        "required": ["summary"],
        "additionalProperties": False,
    }
    config = {
        "schemaVersion": 1,
        "stages": [
            {
                "key": "manager",
                "name": "主管审批",
                "mode": "serial",
                "approverIds": [actor.id],
                "allowBeforeSign": True,
                "allowAfterSign": True,
            }
        ],
        "handlerIds": [actor.id],
    }
    service = Service.objects.create(
        name="数据库申请",
        domain="example.com",
        team_id=7,
        status=Service.Status.PUBLISHED,
        current_version=1,
        form_schema=schema,
        workflow_config=config,
        created_by="admin",
        updated_by="admin",
    )
    version = ServiceVersion.objects.create(
        service=service,
        version=1,
        source_revision=0,
        form_schema=schema,
        workflow_config=config,
        content_hash="a" * 64,
        publish_status=ServiceVersion.PublishStatus.READY,
        engine_process_definition_id="definition-1",
        created_by="admin",
        domain="example.com",
    )
    ticket = Ticket.objects.create(
        number="ITSM-TASK",
        service=service,
        service_version=version,
        domain="example.com",
        team_id=7,
        requester_user_id=99,
        requester_username="requester",
        request_key="task-request",
        request_fingerprint="b" * 64,
        form_data={"summary": "测试"},
        status=Ticket.Status.APPROVING,
        engine_process_instance_id="process-1",
    )
    task = TaskProjection.objects.create(
        ticket=ticket,
        engine_task_id="task-1",
        logical_key="child-1:review",
        task_type=TaskProjection.Type.APPROVAL,
        title="主管审批",
        domain="example.com",
        team_id=7,
        assignee_user_id=actor.id,
        stage_key="manager",
        allow_before_sign=True,
        allow_after_sign=True,
    )
    return actor, target, outsider, ticket, task


def request(method, path, user, data=None):
    factory = APIRequestFactory()
    value = getattr(factory, method)(path, data or {}, format="json")
    value.COOKIES["current_team"] = "7"
    force_authenticate(value, user=user)
    return value


@pytest.mark.django_db
def test_todo_list_only_returns_current_assignee(task_case):
    actor, _, outsider, _, task = task_case
    list_view = TaskViewSet.as_view({"get": "list"})

    actor_response = list_view(request("get", "/tasks/", actor))
    outsider_response = list_view(request("get", "/tasks/", outsider))

    assert [item["id"] for item in actor_response.data["items"]] == [str(task.id)]
    assert outsider_response.data["items"] == []


@pytest.mark.django_db
def test_before_sign_creates_frozen_task_command_from_authenticated_actor(task_case):
    actor, target, _, _, task = task_case
    act = TaskViewSet.as_view({"post": "act"})

    response = act(
        request(
            "post",
            f"/tasks/{task.id}/act/",
            actor,
            {
                "request_id": "before-001",
                "action": "before_sign",
                "user_ids": [target.id],
                "reason": "请安全同事先确认",
                "actor_user_id": 999,
            },
        ),
        pk=task.id,
    )

    assert response.status_code == 202
    command = Command.objects.get(command_type=Command.Type.COMPLETE_TASK)
    task.refresh_from_db()
    assert task.status == TaskProjection.Status.SUBMITTING
    assert command.target_id == "task-1"
    assert command.request_payload["action"] == "before_sign"
    variables = {item["name"]: item["value"] for item in command.request_payload["variables"]}
    assert variables["intent"] == "before"
    assert variables["signUsers"] == [str(target.id)]
    receipt_variable = command.request_payload["receipt_variable"]
    assert receipt_variable.startswith("itsmReceipt_")
    assert variables[receipt_variable] == command.receipt_key
    assert command.request_payload["actor_user_id"] == actor.id


@pytest.mark.django_db
def test_after_sign_plan_is_applied_when_original_approval_is_enqueued(task_case):
    actor, target, _, _, task = task_case
    act = TaskViewSet.as_view({"post": "act"})

    planned = act(
        request(
            "post",
            f"/tasks/{task.id}/act/",
            actor,
            {"request_id": "after-001", "action": "after_sign", "user_ids": [target.id], "reason": "通过后复核"},
        ),
        pk=task.id,
    )
    approved = act(
        request(
            "post",
            f"/tasks/{task.id}/act/",
            actor,
            {"request_id": "approve-001", "action": "approve", "reason": "同意"},
        ),
        pk=task.id,
    )

    assert planned.status_code == 200
    assert approved.status_code == 202
    assert SignPlan.objects.get(ticket=task.ticket).user_ids == [target.id]
    command = Command.objects.get(command_type=Command.Type.COMPLETE_TASK)
    variables = {item["name"]: item["value"] for item in command.request_payload["variables"]}
    assert variables["hasPost"] is True
    assert variables["postUsers"] == [str(target.id)]


@pytest.mark.django_db
def test_other_user_cannot_act_and_repeat_request_is_idempotent(task_case):
    actor, _, outsider, _, task = task_case
    act = TaskViewSet.as_view({"post": "act"})
    payload = {"request_id": "approve-001", "action": "approve", "reason": "同意"}

    denied = act(request("post", f"/tasks/{task.id}/act/", outsider, payload), pk=task.id)
    first = act(request("post", f"/tasks/{task.id}/act/", actor, payload), pk=task.id)
    repeated = act(request("post", f"/tasks/{task.id}/act/", actor, payload), pk=task.id)

    assert denied.status_code == 404
    assert first.status_code == 202
    assert repeated.status_code == 202
    assert repeated.data["command_id"] == first.data["command_id"]
    assert Command.objects.filter(command_type=Command.Type.COMPLETE_TASK).count() == 1
