from datetime import timedelta

import pytest
from django.utils import timezone

from apps.itsm.models import Command, Service, ServiceVersion, TaskProjection, Ticket
from apps.itsm.services.dispatcher import claim_command, dispatch_command, finalize_command_success
from apps.itsm.services.flowable import FlowableConnectionUnavailable, FlowableRejected, FlowableUnavailable


def create_deploy_command():
    service = Service.objects.create(
        name="数据库申请",
        domain="example.com",
        team_id=7,
        form_schema={
            "type": "object",
            "properties": {"summary": {"type": "string", "title": "摘要", "maxLength": 120}},
            "required": ["summary"],
            "additionalProperties": False,
        },
        workflow_config={
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
        created_by="admin",
        updated_by="admin",
    )
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
        idempotency_key="deploy:service:1:version:1",
        fingerprint=version.content_hash,
        request_payload={
            "service_version_id": version.id,
            "deployment_name": "itsm_service_1_v1",
            "process_key": "itsm_service_1_v1",
        },
    )
    return service, version, command


class SuccessfulClient:
    def __init__(self):
        self.deployed = 0

    def deploy_archive(self, name, archive, *, process_key):
        self.deployed += 1
        assert archive.startswith(b"PK")
        return {"deployment_id": "deployment-1", "process_definition_id": f"{process_key}:1:99"}

    def find_deployment(self, name, *, process_key):
        return None


@pytest.mark.django_db
def test_old_lease_cannot_finalize_after_new_executor_claims():
    _, _, command = create_deploy_command()
    first = claim_command(command.id, now=timezone.now(), lease_seconds=1)
    assert first is not None
    Command.objects.filter(pk=command.id).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
    second = claim_command(command.id, now=timezone.now(), lease_seconds=30)
    assert second is not None

    assert finalize_command_success(command.id, first.lease_token, {"deployment_id": "old"}) is False
    assert finalize_command_success(command.id, second.lease_token, {"deployment_id": "new"}) is True
    command.refresh_from_db()
    assert command.result == {"deployment_id": "new"}


@pytest.mark.django_db
def test_dispatch_deployment_updates_version_and_service_atomically():
    service, version, command = create_deploy_command()
    client = SuccessfulClient()

    dispatch_command(command.id, client=client)

    command.refresh_from_db()
    version.refresh_from_db()
    service.refresh_from_db()
    assert command.status == Command.Status.SUCCEEDED
    assert version.publish_status == ServiceVersion.PublishStatus.READY
    assert version.engine_deployment_id == "deployment-1"
    assert service.current_version == 1
    assert service.status == Service.Status.PUBLISHED
    assert client.deployed == 1


@pytest.mark.django_db
def test_connect_failure_is_retryable_and_clears_send_marker():
    _, version, command = create_deploy_command()

    class OfflineClient(SuccessfulClient):
        def deploy_archive(self, name, archive, *, process_key):
            raise FlowableConnectionUnavailable("offline")

    dispatch_command(command.id, client=OfflineClient())

    command.refresh_from_db()
    version.refresh_from_db()
    assert command.status == Command.Status.RETRY
    assert command.sent_at is None
    assert command.next_attempt_at is not None
    assert version.publish_status == ServiceVersion.PublishStatus.PENDING


@pytest.mark.django_db
def test_ambiguous_failure_is_held_for_reconciliation_without_resend():
    _, version, command = create_deploy_command()

    class AmbiguousClient(SuccessfulClient):
        def deploy_archive(self, name, archive, *, process_key):
            raise FlowableUnavailable("timeout")

    client = AmbiguousClient()
    dispatch_command(command.id, client=client)

    command.refresh_from_db()
    version.refresh_from_db()
    assert command.status == Command.Status.UNCERTAIN
    assert command.sent_at is not None
    assert command.next_attempt_at is not None
    assert version.publish_status == ServiceVersion.PublishStatus.DEPLOYING


def create_start_command():
    service, version, _ = create_deploy_command()
    version.publish_status = ServiceVersion.PublishStatus.READY
    version.engine_process_definition_id = "itsm_service_1_v1:1:99"
    version.save(update_fields=("publish_status", "engine_process_definition_id"))
    ticket = Ticket.objects.create(
        number="ITSM-START",
        service=service,
        service_version=version,
        domain="example.com",
        team_id=7,
        requester_user_id=1,
        requester_username="alice",
        request_key="start-request",
        request_fingerprint="b" * 64,
        form_data={"summary": "测试"},
    )
    command = Command.objects.create(
        ticket=ticket,
        service_version=version,
        command_type=Command.Type.START_TICKET,
        idempotency_key=f"start:{ticket.id}",
        fingerprint=ticket.request_fingerprint,
        request_payload={
            "process_definition_id": version.engine_process_definition_id,
            "business_key": str(ticket.id),
            "variables": [{"name": "approval_manager", "value": ["11"], "type": "json"}],
        },
    )
    return ticket, command


@pytest.mark.django_db
def test_dispatch_start_creates_ticket_task_projection():
    ticket, command = create_start_command()

    class StartClient:
        def start_process(self, definition_id, *, business_key, variables):
            return {"id": "process-1"}

        def historic_processes(self, *, business_key):
            return []

        def active_tasks(self, root_process_instance_id):
            return [
                {
                    "id": "task-1",
                    "process_instance_id": "child-1",
                    "definition_key": "review",
                    "name": "主管审批",
                    "assignee": "11",
                    "stage_key": "manager",
                    "depth": 0,
                    "allow_before_sign": True,
                    "allow_after_sign": True,
                }
            ]

    dispatch_command(command.id, client=StartClient())

    ticket.refresh_from_db()
    command.refresh_from_db()
    task = TaskProjection.objects.get(ticket=ticket)
    assert command.status == Command.Status.SUCCEEDED
    assert ticket.engine_process_instance_id == "process-1"
    assert ticket.status == Ticket.Status.APPROVING
    assert task.engine_task_id == "task-1"
    assert task.assignee_user_id == 11
    assert task.allow_before_sign is True


@pytest.mark.django_db
def test_sent_start_is_reconciled_without_starting_again():
    ticket, command = create_start_command()
    command.status = Command.Status.UNCERTAIN
    command.sent_at = timezone.now()
    command.next_attempt_at = timezone.now() - timedelta(seconds=1)
    command.save(update_fields=("status", "sent_at", "next_attempt_at"))

    class ReconcileClient:
        started = 0

        def start_process(self, definition_id, *, business_key, variables):
            self.started += 1
            return {"id": "duplicate"}

        def historic_processes(self, *, business_key):
            return [{"id": "process-existing"}]

        def active_tasks(self, root_process_instance_id):
            return []

        def process_result(self, process_instance_id):
            return "running"

    client = ReconcileClient()
    dispatch_command(command.id, client=client)

    ticket.refresh_from_db()
    command.refresh_from_db()
    assert command.status == Command.Status.SUCCEEDED
    assert ticket.engine_process_instance_id == "process-existing"
    assert client.started == 0


@pytest.mark.django_db
def test_complete_handling_moves_ticket_to_waiting_confirmation():
    ticket, _ = create_start_command()
    ticket.engine_process_instance_id = "process-1"
    ticket.status = Ticket.Status.PROCESSING
    ticket.save(update_fields=("engine_process_instance_id", "status"))
    task = TaskProjection.objects.create(
        ticket=ticket,
        engine_task_id="handle-1",
        logical_key="process-1:handle",
        task_type=TaskProjection.Type.HANDLING,
        title="处理工单",
        domain="example.com",
        team_id=7,
        assignee_user_id=21,
        status=TaskProjection.Status.SUBMITTING,
    )
    command = Command.objects.create(
        ticket=ticket,
        service_version=ticket.service_version,
        command_type=Command.Type.COMPLETE_TASK,
        idempotency_key="complete:handle-1",
        fingerprint="c" * 64,
        target_id="handle-1",
        receipt_key="receipt-1",
        request_payload={
            "action": "complete_handling",
            "task_projection_id": str(task.id),
            "actor_user_id": 21,
            "reason": "处理完成",
            "receipt_variable": "itsmReceipt_11111111111111111111111111111111",
            "variables": [
                {
                    "name": "itsmReceipt_11111111111111111111111111111111",
                    "value": "receipt-1",
                    "type": "string",
                }
            ],
        },
    )

    class CompleteClient:
        completed = 0

        def complete_task(self, task_id, *, variables):
            self.completed += 1

        def active_tasks(self, root_process_instance_id):
            return []

        def process_result(self, process_instance_id):
            return "completed"

    client = CompleteClient()
    dispatch_command(command.id, client=client)

    ticket.refresh_from_db()
    task.refresh_from_db()
    command.refresh_from_db()
    assert client.completed == 1
    assert command.status == Command.Status.SUCCEEDED
    assert task.status == TaskProjection.Status.COMPLETED
    assert ticket.status == Ticket.Status.WAITING_CONFIRMATION
    assert ticket.resolved_at is not None


@pytest.mark.django_db
def test_sent_task_command_uses_receipt_and_does_not_complete_again():
    ticket, _ = create_start_command()
    ticket.engine_process_instance_id = "process-1"
    ticket.save(update_fields=("engine_process_instance_id",))
    task = TaskProjection.objects.create(
        ticket=ticket,
        engine_task_id="task-approval",
        logical_key="child-1:review",
        task_type=TaskProjection.Type.APPROVAL,
        title="审批",
        domain="example.com",
        team_id=7,
        assignee_user_id=11,
        status=TaskProjection.Status.SUBMITTING,
    )
    command = Command.objects.create(
        ticket=ticket,
        service_version=ticket.service_version,
        command_type=Command.Type.COMPLETE_TASK,
        idempotency_key="complete:approval",
        fingerprint="d" * 64,
        target_id="task-approval",
        receipt_key="receipt-approval",
        status=Command.Status.UNCERTAIN,
        sent_at=timezone.now(),
        next_attempt_at=timezone.now() - timedelta(seconds=1),
        request_payload={
            "action": "approve",
            "task_projection_id": str(task.id),
            "actor_user_id": 11,
            "reason": "同意",
            "receipt_variable": "itsmReceipt_22222222222222222222222222222222",
            "variables": [],
        },
    )

    class ReceiptClient:
        completed = 0

        def historic_receipt(self, variable_name):
            assert variable_name == "itsmReceipt_22222222222222222222222222222222"
            return "receipt-approval"

        def task_exists(self, task_id):
            return False

        def complete_task(self, task_id, *, variables):
            self.completed += 1

        def active_tasks(self, root_process_instance_id):
            return [
                {
                    "id": "handle-new",
                    "process_instance_id": "process-1",
                    "definition_key": "handle",
                    "name": "处理工单",
                    "assignee": "21",
                    "stage_key": "",
                    "depth": 0,
                    "allow_before_sign": False,
                    "allow_after_sign": False,
                }
            ]

    client = ReceiptClient()
    dispatch_command(command.id, client=client)

    command.refresh_from_db()
    ticket.refresh_from_db()
    assert command.status == Command.Status.SUCCEEDED
    assert client.completed == 0
    assert ticket.status == Ticket.Status.PROCESSING
    assert TaskProjection.objects.filter(ticket=ticket, engine_task_id="handle-new").exists()


def create_task_command(*, status=Command.Status.PENDING, sent=False):
    ticket, _ = create_start_command()
    ticket.engine_process_instance_id = "process-task"
    ticket.status = Ticket.Status.APPROVING
    ticket.save(update_fields=("engine_process_instance_id", "status"))
    task = TaskProjection.objects.create(
        ticket=ticket,
        engine_task_id="task-retry",
        logical_key="child-retry:review",
        task_type=TaskProjection.Type.APPROVAL,
        title="审批",
        domain="example.com",
        team_id=7,
        assignee_user_id=11,
        status=TaskProjection.Status.SUBMITTING,
    )
    command = Command.objects.create(
        ticket=ticket,
        service_version=ticket.service_version,
        command_type=Command.Type.COMPLETE_TASK,
        idempotency_key="complete:retry",
        fingerprint="e" * 64,
        target_id=task.engine_task_id,
        receipt_key="receipt-retry",
        status=status,
        sent_at=timezone.now() if sent else None,
        next_attempt_at=timezone.now() - timedelta(seconds=1) if sent else None,
        request_payload={
            "action": "approve",
            "task_projection_id": str(task.id),
            "actor_user_id": 11,
            "reason": "同意",
            "receipt_variable": "itsmReceipt_33333333333333333333333333333333",
            "variables": [],
        },
    )
    return ticket, task, command


@pytest.mark.django_db
def test_task_delivery_failure_does_not_change_published_version_state():
    ticket, task, command = create_task_command()

    class RejectedClient:
        def complete_task(self, task_id, *, variables):
            raise FlowableRejected("invalid task")

    dispatch_command(command.id, client=RejectedClient())

    command.refresh_from_db()
    task.refresh_from_db()
    ticket.service_version.refresh_from_db()
    assert command.status == Command.Status.FAILED
    assert task.status == TaskProjection.Status.PENDING
    assert ticket.service_version.publish_status == ServiceVersion.PublishStatus.READY


@pytest.mark.django_db
def test_task_connection_retry_does_not_reset_published_version_state():
    ticket, task, command = create_task_command()

    class OfflineClient:
        def complete_task(self, task_id, *, variables):
            raise FlowableConnectionUnavailable("offline")

    dispatch_command(command.id, client=OfflineClient())

    command.refresh_from_db()
    task.refresh_from_db()
    ticket.service_version.refresh_from_db()
    assert command.status == Command.Status.RETRY
    assert command.sent_at is None
    assert task.status == TaskProjection.Status.SUBMITTING
    assert ticket.service_version.publish_status == ServiceVersion.PublishStatus.READY


@pytest.mark.django_db
def test_max_attempts_failure_releases_task_for_explicit_retry():
    _, task, command = create_task_command()
    command.attempts = command.max_attempts
    command.save(update_fields=("attempts",))

    assert claim_command(command.id) is None

    command.refresh_from_db()
    task.refresh_from_db()
    assert command.status == Command.Status.FAILED
    assert command.last_error == "MAX_ATTEMPTS_EXCEEDED"
    assert task.status == TaskProjection.Status.PENDING


@pytest.mark.django_db
def test_uncertain_task_without_receipt_retries_only_when_original_task_exists():
    _, task, command = create_task_command(status=Command.Status.UNCERTAIN, sent=True)

    class ExistingTaskClient:
        completed = 0

        def historic_receipt(self, variable_name):
            return None

        def task_exists(self, task_id):
            return True

        def complete_task(self, task_id, *, variables):
            self.completed += 1

        def active_tasks(self, root_process_instance_id):
            return []

        def process_result(self, process_instance_id):
            return "rejected"

    client = ExistingTaskClient()
    dispatch_command(command.id, client=client)

    command.refresh_from_db()
    task.refresh_from_db()
    assert client.completed == 1
    assert command.status == Command.Status.SUCCEEDED
    assert task.status == TaskProjection.Status.COMPLETED


@pytest.mark.django_db
def test_uncertain_task_that_ended_without_receipt_requires_attention():
    _, task, command = create_task_command(status=Command.Status.UNCERTAIN, sent=True)

    class MissingTaskClient:
        def historic_receipt(self, variable_name):
            return None

        def task_exists(self, task_id):
            return False

    dispatch_command(command.id, client=MissingTaskClient())

    command.refresh_from_db()
    task.refresh_from_db()
    assert command.status == Command.Status.FAILED
    assert command.last_error == "TASK_ENDED_WITHOUT_RECEIPT"
    assert task.status == TaskProjection.Status.CANCELLED
