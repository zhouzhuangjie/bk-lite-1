from __future__ import annotations

from rest_framework import serializers

from apps.itsm.models import AuditEvent, Service, ServiceVersion, TaskProjection, Ticket
from apps.itsm.services.validation import ITSMValidationError, validate_form_schema, validate_workflow_config


class ServiceSerializer(serializers.ModelSerializer):
    has_draft = serializers.SerializerMethodField()

    @staticmethod
    def get_has_draft(service: Service) -> bool:
        return service.current_version == 0 or service.draft_revision != service.last_published_revision

    def validate_form_schema(self, value):
        try:
            return validate_form_schema(value)
        except ITSMValidationError as error:
            raise serializers.ValidationError(str(error)) from error

    def validate_workflow_config(self, value):
        try:
            return validate_workflow_config(value)
        except ITSMValidationError as error:
            raise serializers.ValidationError(str(error)) from error

    class Meta:
        model = Service
        fields = (
            "id",
            "name",
            "description",
            "team_id",
            "status",
            "form_schema",
            "workflow_config",
            "draft_revision",
            "last_published_revision",
            "current_version",
            "has_draft",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "team_id",
            "status",
            "draft_revision",
            "last_published_revision",
            "current_version",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        )


class ServiceVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceVersion
        fields = (
            "id",
            "service_id",
            "version",
            "source_revision",
            "form_schema",
            "workflow_config",
            "content_hash",
            "publish_status",
            "publish_error",
            "created_by",
            "created_at",
        )
        read_only_fields = fields


class CatalogServiceSerializer(serializers.ModelSerializer):
    form_schema = serializers.SerializerMethodField()
    workflow_config = serializers.SerializerMethodField()

    @staticmethod
    def get_form_schema(service: Service) -> dict:
        version = getattr(service, "current_published_version", None)
        return version.form_schema if version is not None else {}

    @staticmethod
    def get_workflow_config(service: Service) -> dict:
        version = getattr(service, "current_published_version", None)
        return version.workflow_config if version is not None else {"schemaVersion": 1, "stages": [], "handlerIds": []}

    class Meta:
        model = Service
        fields = (
            "id",
            "name",
            "description",
            "team_id",
            "current_version",
            "form_schema",
            "workflow_config",
            "updated_at",
        )
        read_only_fields = fields


class TicketCreateSerializer(serializers.Serializer):
    service_id = serializers.IntegerField(min_value=1)
    request_key = serializers.RegexField(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    form_data = serializers.DictField()


class AuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvent
        fields = (
            "id",
            "actor_user_id",
            "actor_username",
            "action",
            "from_status",
            "to_status",
            "reason",
            "detail",
            "created_at",
        )
        read_only_fields = fields


class TicketSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source="service.name", read_only=True)
    service_version_number = serializers.IntegerField(source="service_version.version", read_only=True)
    form_schema = serializers.JSONField(source="service_version.form_schema", read_only=True)
    workflow_config = serializers.JSONField(source="service_version.workflow_config", read_only=True)
    audit_events = AuditEventSerializer(many=True, read_only=True)

    class Meta:
        model = Ticket
        fields = (
            "id",
            "number",
            "service_id",
            "service_name",
            "service_version_number",
            "form_schema",
            "workflow_config",
            "team_id",
            "requester_user_id",
            "requester_username",
            "form_data",
            "status",
            "resolved_at",
            "closed_at",
            "audit_events",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class TaskProjectionSerializer(serializers.ModelSerializer):
    ticket_number = serializers.CharField(source="ticket.number", read_only=True)
    service_name = serializers.CharField(source="ticket.service.name", read_only=True)
    requester_username = serializers.CharField(source="ticket.requester_username", read_only=True)
    ticket_status = serializers.CharField(source="ticket.status", read_only=True)
    form_data = serializers.JSONField(source="ticket.form_data", read_only=True)
    form_schema = serializers.JSONField(source="ticket.service_version.form_schema", read_only=True)

    class Meta:
        model = TaskProjection
        fields = (
            "id",
            "ticket_id",
            "ticket_number",
            "service_name",
            "requester_username",
            "ticket_status",
            "form_data",
            "form_schema",
            "task_type",
            "title",
            "status",
            "stage_key",
            "allow_before_sign",
            "allow_after_sign",
            "sign_parent_key",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class TaskActionSerializer(serializers.Serializer):
    request_id = serializers.RegexField(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    action = serializers.ChoiceField(choices=("approve", "reject", "before_sign", "after_sign", "complete_handling"))
    user_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        default=list,
        max_length=20,
    )
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=500, trim_whitespace=False)
