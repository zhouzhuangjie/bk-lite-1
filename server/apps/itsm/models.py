from __future__ import annotations

import uuid

from django.db import models

from apps.core.models.maintainer_info import MaintainerInfo
from apps.core.models.time_info import TimeInfo


class Service(TimeInfo, MaintainerInfo):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "草稿"
        PUBLISHED = "PUBLISHED", "已发布"
        DISABLED = "DISABLED", "已停用"

    name = models.CharField(max_length=120)
    description = models.CharField(max_length=500, blank=True, default="")
    team_id = models.PositiveBigIntegerField(db_index=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    form_schema = models.JSONField(default=dict)
    workflow_config = models.JSONField(default=dict)
    draft_revision = models.PositiveIntegerField(default=0)
    last_published_revision = models.PositiveIntegerField(default=0)
    current_version = models.PositiveIntegerField(default=0)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "itsm_service"
        ordering = ("-updated_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("domain", "team_id", "name"),
                condition=models.Q(deleted_at__isnull=True),
                name="uq_itsm_service_name_scope",
            )
        ]
        indexes = [models.Index(fields=("domain", "team_id", "status"), name="itsm_service_scope_idx")]


class ServiceVersion(TimeInfo):
    class PublishStatus(models.TextChoices):
        PENDING = "PENDING", "待发布"
        DEPLOYING = "DEPLOYING", "发布中"
        READY = "READY", "可用"
        FAILED = "FAILED", "发布失败"

    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    source_revision = models.PositiveIntegerField()
    form_schema = models.JSONField(default=dict)
    workflow_config = models.JSONField(default=dict)
    content_hash = models.CharField(max_length=64)
    publish_status = models.CharField(max_length=16, choices=PublishStatus.choices, default=PublishStatus.PENDING, db_index=True)
    engine_deployment_id = models.CharField(max_length=128, blank=True, default="")
    engine_process_definition_id = models.CharField(max_length=128, blank=True, default="")
    publish_error = models.CharField(max_length=500, blank=True, default="")
    created_by = models.CharField(max_length=150)
    domain = models.CharField(max_length=100, db_index=True)

    class Meta:
        db_table = "itsm_service_version"
        ordering = ("-version",)
        constraints = [
            models.UniqueConstraint(fields=("service", "version"), name="uq_itsm_service_version"),
            models.UniqueConstraint(fields=("service", "source_revision"), name="uq_itsm_version_revision"),
        ]
        indexes = [models.Index(fields=("service", "publish_status"), name="itsm_version_status_idx")]


class Ticket(TimeInfo):
    class Status(models.TextChoices):
        SUBMITTING = "SUBMITTING", "提交中"
        APPROVING = "APPROVING", "审批中"
        PROCESSING = "PROCESSING", "处理中"
        WAITING_CONFIRMATION = "WAITING_CONFIRMATION", "待确认"
        CLOSED = "CLOSED", "已关闭"
        REJECTED = "REJECTED", "已驳回"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=32, unique=True)
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="tickets")
    service_version = models.ForeignKey(ServiceVersion, on_delete=models.PROTECT, related_name="tickets")
    domain = models.CharField(max_length=100, db_index=True)
    team_id = models.PositiveBigIntegerField(db_index=True)
    requester_user_id = models.PositiveBigIntegerField(db_index=True)
    requester_username = models.CharField(max_length=150)
    request_key = models.CharField(max_length=128)
    request_fingerprint = models.CharField(max_length=64)
    form_data = models.JSONField(default=dict)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.SUBMITTING, db_index=True)
    engine_process_instance_id = models.CharField(max_length=128, null=True, blank=True, unique=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "itsm_ticket"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("domain", "requester_user_id", "request_key"),
                name="uq_itsm_ticket_request",
            )
        ]
        indexes = [
            models.Index(fields=("domain", "team_id", "status", "created_at"), name="itsm_ticket_scope_idx"),
            models.Index(fields=("domain", "requester_user_id", "created_at"), name="itsm_ticket_owner_idx"),
        ]


class TaskProjection(TimeInfo):
    class Type(models.TextChoices):
        APPROVAL = "APPROVAL", "审批"
        HANDLING = "HANDLING", "处理"

    class Status(models.TextChoices):
        PENDING = "PENDING", "待处理"
        SUBMITTING = "SUBMITTING", "提交中"
        COMPLETED = "COMPLETED", "已完成"
        CANCELLED = "CANCELLED", "已取消"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="tasks")
    engine_task_id = models.CharField(max_length=128, unique=True)
    logical_key = models.CharField(max_length=128, db_index=True)
    task_type = models.CharField(max_length=16, choices=Type.choices)
    title = models.CharField(max_length=120)
    domain = models.CharField(max_length=100, db_index=True)
    team_id = models.PositiveBigIntegerField(db_index=True)
    assignee_user_id = models.PositiveBigIntegerField(db_index=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    stage_key = models.CharField(max_length=64, blank=True, default="")
    allow_before_sign = models.BooleanField(default=False)
    allow_after_sign = models.BooleanField(default=False)
    sign_parent_key = models.CharField(max_length=128, blank=True, default="")
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "itsm_task_projection"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("domain", "team_id", "assignee_user_id", "status"), name="itsm_task_todo_idx"),
            models.Index(fields=("ticket", "logical_key", "status"), name="itsm_task_ticket_idx"),
        ]


class Command(TimeInfo):
    class Type(models.TextChoices):
        DEPLOY_VERSION = "DEPLOY_VERSION", "发布服务版本"
        START_TICKET = "START_TICKET", "启动工单"
        COMPLETE_TASK = "COMPLETE_TASK", "完成人工任务"
        PLAN_AFTER_SIGN = "PLAN_AFTER_SIGN", "保存后加签计划"
        RECONCILE_TICKET = "RECONCILE_TICKET", "核对工单状态"

    class Status(models.TextChoices):
        PENDING = "PENDING", "待发送"
        DELIVERING = "DELIVERING", "发送中"
        SUCCEEDED = "SUCCEEDED", "成功"
        RETRY = "RETRY", "待重试"
        UNCERTAIN = "UNCERTAIN", "结果待核对"
        FAILED = "FAILED", "失败"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service_version = models.ForeignKey(ServiceVersion, on_delete=models.PROTECT, null=True, blank=True, related_name="commands")
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, null=True, blank=True, related_name="commands")
    command_type = models.CharField(max_length=32, choices=Type.choices, db_index=True)
    idempotency_key = models.CharField(max_length=255, unique=True)
    fingerprint = models.CharField(max_length=64)
    target_id = models.CharField(max_length=128, blank=True, default="")
    request_payload = models.JSONField(default=dict)
    receipt_key = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=10)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    lease_token = models.UUIDField(null=True, blank=True, editable=False)
    lease_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(default=dict)
    last_error = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        db_table = "itsm_command"
        ordering = ("created_at", "id")
        indexes = [
            models.Index(fields=("status", "next_attempt_at"), name="itsm_command_due_idx"),
            models.Index(fields=("status", "lease_expires_at"), name="itsm_command_lease_idx"),
            models.Index(fields=("ticket", "status"), name="itsm_command_ticket_idx"),
        ]


class AuditEvent(TimeInfo):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="audit_events")
    command = models.ForeignKey(Command, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_events")
    actor_user_id = models.PositiveBigIntegerField(null=True, blank=True)
    actor_username = models.CharField(max_length=150, blank=True, default="")
    actor_domain = models.CharField(max_length=100)
    action = models.CharField(max_length=64, db_index=True)
    from_status = models.CharField(max_length=32, blank=True, default="")
    to_status = models.CharField(max_length=32, blank=True, default="")
    reason = models.CharField(max_length=500, blank=True, default="")
    detail = models.JSONField(default=dict)

    class Meta:
        db_table = "itsm_audit_event"
        ordering = ("created_at", "id")
        indexes = [models.Index(fields=("ticket", "created_at"), name="itsm_audit_ticket_idx")]


class SignPlan(TimeInfo):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="sign_plans")
    task_logical_key = models.CharField(max_length=128)
    user_ids = models.JSONField(default=list)
    created_by_user_id = models.PositiveBigIntegerField()
    created_by_username = models.CharField(max_length=150)
    created_by_domain = models.CharField(max_length=100)
    reason = models.CharField(max_length=500)
    applied = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = "itsm_sign_plan"
        constraints = [models.UniqueConstraint(fields=("ticket", "task_logical_key"), name="uq_itsm_sign_plan_task")]
