import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="AuditEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Created Time")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Updated Time")),
                ("actor_user_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("actor_username", models.CharField(blank=True, default="", max_length=150)),
                ("actor_domain", models.CharField(max_length=100)),
                ("action", models.CharField(db_index=True, max_length=64)),
                ("from_status", models.CharField(blank=True, default="", max_length=32)),
                ("to_status", models.CharField(blank=True, default="", max_length=32)),
                ("reason", models.CharField(blank=True, default="", max_length=500)),
                ("detail", models.JSONField(default=dict)),
            ],
            options={
                "db_table": "itsm_audit_event",
                "ordering": ("created_at", "id"),
            },
        ),
        migrations.CreateModel(
            name="Command",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Created Time")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Updated Time")),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "command_type",
                    models.CharField(
                        choices=[("DEPLOY_VERSION", "发布服务版本"), ("START_TICKET", "启动工单"), ("COMPLETE_TASK", "完成人工任务"), ("RECONCILE_TICKET", "核对工单状态")],
                        db_index=True,
                        max_length=32,
                    ),
                ),
                ("idempotency_key", models.CharField(max_length=255, unique=True)),
                ("fingerprint", models.CharField(max_length=64)),
                ("target_id", models.CharField(blank=True, default="", max_length=128)),
                ("request_payload", models.JSONField(default=dict)),
                ("receipt_key", models.CharField(blank=True, default="", max_length=255)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "待发送"),
                            ("DELIVERING", "发送中"),
                            ("SUCCEEDED", "成功"),
                            ("RETRY", "待重试"),
                            ("UNCERTAIN", "结果待核对"),
                            ("FAILED", "失败"),
                        ],
                        db_index=True,
                        default="PENDING",
                        max_length=16,
                    ),
                ),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("max_attempts", models.PositiveIntegerField(default=10)),
                ("next_attempt_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("lease_token", models.UUIDField(blank=True, editable=False, null=True)),
                ("lease_expires_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("result", models.JSONField(default=dict)),
                ("last_error", models.CharField(blank=True, default="", max_length=500)),
            ],
            options={
                "db_table": "itsm_command",
                "ordering": ("created_at", "id"),
            },
        ),
        migrations.CreateModel(
            name="Service",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Created Time")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Updated Time")),
                ("created_by", models.CharField(default="", max_length=32, verbose_name="Creator")),
                ("updated_by", models.CharField(default="", max_length=32, verbose_name="Updater")),
                ("domain", models.CharField(default="domain.com", max_length=100, verbose_name="Domain")),
                ("updated_by_domain", models.CharField(default="domain.com", max_length=100, verbose_name="updated by domain")),
                ("name", models.CharField(max_length=120)),
                ("description", models.CharField(blank=True, default="", max_length=500)),
                ("team_id", models.PositiveBigIntegerField(db_index=True)),
                (
                    "status",
                    models.CharField(
                        choices=[("DRAFT", "草稿"), ("PUBLISHED", "已发布"), ("DISABLED", "已停用")], db_index=True, default="DRAFT", max_length=16
                    ),
                ),
                ("form_schema", models.JSONField(default=dict)),
                ("workflow_config", models.JSONField(default=dict)),
                ("draft_revision", models.PositiveIntegerField(default=0)),
                ("last_published_revision", models.PositiveIntegerField(default=0)),
                ("current_version", models.PositiveIntegerField(default=0)),
                ("deleted_at", models.DateTimeField(blank=True, db_index=True, null=True)),
            ],
            options={
                "db_table": "itsm_service",
                "ordering": ("-updated_at", "-id"),
            },
        ),
        migrations.CreateModel(
            name="ServiceVersion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Created Time")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Updated Time")),
                ("version", models.PositiveIntegerField()),
                ("source_revision", models.PositiveIntegerField()),
                ("form_schema", models.JSONField(default=dict)),
                ("workflow_config", models.JSONField(default=dict)),
                ("content_hash", models.CharField(max_length=64)),
                (
                    "publish_status",
                    models.CharField(
                        choices=[("PENDING", "待发布"), ("DEPLOYING", "发布中"), ("READY", "可用"), ("FAILED", "发布失败")],
                        db_index=True,
                        default="PENDING",
                        max_length=16,
                    ),
                ),
                ("engine_deployment_id", models.CharField(blank=True, default="", max_length=128)),
                ("engine_process_definition_id", models.CharField(blank=True, default="", max_length=128)),
                ("publish_error", models.CharField(blank=True, default="", max_length=500)),
                ("created_by", models.CharField(max_length=150)),
                ("domain", models.CharField(db_index=True, max_length=100)),
                ("service", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="versions", to="itsm.service")),
            ],
            options={
                "db_table": "itsm_service_version",
                "ordering": ("-version",),
            },
        ),
        migrations.CreateModel(
            name="Ticket",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Created Time")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Updated Time")),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("number", models.CharField(max_length=32, unique=True)),
                ("domain", models.CharField(db_index=True, max_length=100)),
                ("team_id", models.PositiveBigIntegerField(db_index=True)),
                ("requester_user_id", models.PositiveBigIntegerField(db_index=True)),
                ("requester_username", models.CharField(max_length=150)),
                ("request_key", models.CharField(max_length=128)),
                ("request_fingerprint", models.CharField(max_length=64)),
                ("form_data", models.JSONField(default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("SUBMITTING", "提交中"),
                            ("APPROVING", "审批中"),
                            ("PROCESSING", "处理中"),
                            ("WAITING_CONFIRMATION", "待确认"),
                            ("CLOSED", "已关闭"),
                            ("REJECTED", "已驳回"),
                        ],
                        db_index=True,
                        default="SUBMITTING",
                        max_length=32,
                    ),
                ),
                ("engine_process_instance_id", models.CharField(blank=True, max_length=128, null=True, unique=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("service", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="tickets", to="itsm.service")),
                ("service_version", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="tickets", to="itsm.serviceversion")),
            ],
            options={
                "db_table": "itsm_ticket",
                "ordering": ("-created_at",),
            },
        ),
        migrations.CreateModel(
            name="TaskProjection",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Created Time")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Updated Time")),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("engine_task_id", models.CharField(max_length=128, unique=True)),
                ("logical_key", models.CharField(db_index=True, max_length=128)),
                ("task_type", models.CharField(choices=[("APPROVAL", "审批"), ("HANDLING", "处理")], max_length=16)),
                ("title", models.CharField(max_length=120)),
                ("domain", models.CharField(db_index=True, max_length=100)),
                ("team_id", models.PositiveBigIntegerField(db_index=True)),
                ("assignee_user_id", models.PositiveBigIntegerField(db_index=True)),
                (
                    "status",
                    models.CharField(
                        choices=[("PENDING", "待处理"), ("SUBMITTING", "提交中"), ("COMPLETED", "已完成"), ("CANCELLED", "已取消")],
                        db_index=True,
                        default="PENDING",
                        max_length=16,
                    ),
                ),
                ("stage_key", models.CharField(blank=True, default="", max_length=64)),
                ("allow_before_sign", models.BooleanField(default=False)),
                ("allow_after_sign", models.BooleanField(default=False)),
                ("sign_parent_key", models.CharField(blank=True, default="", max_length=128)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("ticket", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tasks", to="itsm.ticket")),
            ],
            options={
                "db_table": "itsm_task_projection",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="service",
            index=models.Index(fields=["domain", "team_id", "status"], name="itsm_service_scope_idx"),
        ),
        migrations.AddConstraint(
            model_name="service",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True)), fields=("domain", "team_id", "name"), name="uq_itsm_service_name_scope"
            ),
        ),
        migrations.AddField(
            model_name="command",
            name="service_version",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="commands", to="itsm.serviceversion"
            ),
        ),
        migrations.AddField(
            model_name="command",
            name="ticket",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="commands", to="itsm.ticket"),
        ),
        migrations.AddField(
            model_name="auditevent",
            name="command",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="audit_events", to="itsm.command"
            ),
        ),
        migrations.AddField(
            model_name="auditevent",
            name="ticket",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="audit_events", to="itsm.ticket"),
        ),
        migrations.AddIndex(
            model_name="ticket",
            index=models.Index(fields=["domain", "team_id", "status", "created_at"], name="itsm_ticket_scope_idx"),
        ),
        migrations.AddIndex(
            model_name="ticket",
            index=models.Index(fields=["domain", "requester_user_id", "created_at"], name="itsm_ticket_owner_idx"),
        ),
        migrations.AddConstraint(
            model_name="ticket",
            constraint=models.UniqueConstraint(fields=("domain", "requester_user_id", "request_key"), name="uq_itsm_ticket_request"),
        ),
        migrations.AddIndex(
            model_name="taskprojection",
            index=models.Index(fields=["domain", "team_id", "assignee_user_id", "status"], name="itsm_task_todo_idx"),
        ),
        migrations.AddIndex(
            model_name="taskprojection",
            index=models.Index(fields=["ticket", "logical_key", "status"], name="itsm_task_ticket_idx"),
        ),
        migrations.AddIndex(
            model_name="serviceversion",
            index=models.Index(fields=["service", "publish_status"], name="itsm_version_status_idx"),
        ),
        migrations.AddConstraint(
            model_name="serviceversion",
            constraint=models.UniqueConstraint(fields=("service", "version"), name="uq_itsm_service_version"),
        ),
        migrations.AddConstraint(
            model_name="serviceversion",
            constraint=models.UniqueConstraint(fields=("service", "source_revision"), name="uq_itsm_version_revision"),
        ),
        migrations.AddIndex(
            model_name="command",
            index=models.Index(fields=["status", "next_attempt_at"], name="itsm_command_due_idx"),
        ),
        migrations.AddIndex(
            model_name="command",
            index=models.Index(fields=["status", "lease_expires_at"], name="itsm_command_lease_idx"),
        ),
        migrations.AddIndex(
            model_name="command",
            index=models.Index(fields=["ticket", "status"], name="itsm_command_ticket_idx"),
        ),
        migrations.AddIndex(
            model_name="auditevent",
            index=models.Index(fields=["ticket", "created_at"], name="itsm_audit_ticket_idx"),
        ),
    ]
