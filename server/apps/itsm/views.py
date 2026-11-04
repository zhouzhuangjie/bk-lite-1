from __future__ import annotations

from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.core.decorators.api_permission import HasPermission
from apps.itsm.models import AuditEvent, Service, ServiceVersion, TaskProjection, Ticket
from apps.itsm.serializers import (
    CatalogServiceSerializer,
    ServiceSerializer,
    ServiceVersionSerializer,
    TaskActionSerializer,
    TaskProjectionSerializer,
    TicketCreateSerializer,
    TicketSerializer,
)
from apps.itsm.services.publication import publish_service
from apps.itsm.services.scopes import request_scope
from apps.itsm.services.task_actions import TaskActionConflict, TaskActionInvalid, enqueue_task_action
from apps.itsm.services.tickets import TicketConflict, submit_ticket
from apps.itsm.services.validation import ITSMValidationError


class ITSMPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response({"count": self.page.paginator.count, "items": data})


class ServiceViewSet(viewsets.ModelViewSet):
    http_method_names = ["get", "post", "patch", "head", "options"]
    serializer_class = ServiceSerializer
    pagination_class = ITSMPagination
    queryset = Service.objects.none()

    def _queryset(self, request):
        scope = request_scope(request)
        return Service.objects.filter(domain=scope.domain, team_id=scope.team_id, deleted_at__isnull=True).order_by("-updated_at", "-id")

    def _object(self, request, pk, *, refresh_user=False):
        scope = request_scope(request, refresh_user=refresh_user)
        return get_object_or_404(Service, pk=pk, domain=scope.domain, team_id=scope.team_id, deleted_at__isnull=True)

    @HasPermission("service_management-View")
    def list(self, request, *args, **kwargs):
        queryset = self._queryset(request)
        search = str(request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(name__icontains=search[:120])
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    @HasPermission("service_management-View")
    def retrieve(self, request, *args, **kwargs):
        return Response(self.get_serializer(self._object(request, kwargs["pk"])).data)

    @HasPermission("service_management-Add")
    def create(self, request, *args, **kwargs):
        scope = request_scope(request, refresh_user=True)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            service = serializer.save(
                domain=scope.domain,
                team_id=scope.team_id,
                created_by=scope.username,
                updated_by=scope.username,
                updated_by_domain=scope.domain,
            )
        except IntegrityError as error:
            raise ValidationError({"name": "当前组织已存在同名服务"}) from error
        return Response(self.get_serializer(service).data, status=status.HTTP_201_CREATED)

    @HasPermission("service_management-Edit")
    def partial_update(self, request, *args, **kwargs):
        scope = request_scope(request, refresh_user=True)
        supplied_revision = request.data.get("draft_revision")
        if isinstance(supplied_revision, bool) or not isinstance(supplied_revision, int):
            raise ValidationError({"draft_revision": "保存草稿必须携带当前 revision"})

        with transaction.atomic():
            service = (
                Service.objects.select_for_update()
                .filter(
                    pk=kwargs["pk"],
                    domain=scope.domain,
                    team_id=scope.team_id,
                    deleted_at__isnull=True,
                )
                .first()
            )
            if service is None:
                return Response(status=status.HTTP_404_NOT_FOUND)
            if supplied_revision != service.draft_revision:
                return Response(
                    {"detail": "草稿已被其他修改更新", "code": "DRAFT_REVISION_CONFLICT", "draft_revision": service.draft_revision},
                    status=status.HTTP_409_CONFLICT,
                )
            payload = {key: value for key, value in request.data.items() if key != "draft_revision"}
            serializer = self.get_serializer(service, data=payload, partial=True)
            serializer.is_valid(raise_exception=True)
            service = serializer.save(
                draft_revision=service.draft_revision + 1,
                updated_by=scope.username,
                updated_by_domain=scope.domain,
            )
        return Response(self.get_serializer(service).data)

    @action(methods=["POST"], detail=True)
    @HasPermission("service_management-Publish")
    def publish(self, request, pk=None):
        scope = request_scope(request, refresh_user=True)
        if not Service.objects.filter(pk=pk, domain=scope.domain, team_id=scope.team_id, deleted_at__isnull=True).exists():
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            version, command = publish_service(
                int(pk),
                username=scope.username,
                domain=scope.domain,
                team_id=scope.team_id,
            )
        except ITSMValidationError as error:
            raise ValidationError({"detail": str(error)}) from error
        data = ServiceVersionSerializer(version).data
        data["command_id"] = str(command.id)
        return Response(data, status=status.HTTP_202_ACCEPTED)

    @action(methods=["GET"], detail=True)
    @HasPermission("service_management-View")
    def versions(self, request, pk=None):
        service = self._object(request, pk)
        page = self.paginate_queryset(service.versions.order_by("-version"))
        return self.get_paginated_response(ServiceVersionSerializer(page, many=True).data)

    @action(methods=["POST"], detail=True)
    @HasPermission("service_management-Edit")
    def disable(self, request, pk=None):
        scope = request_scope(request, refresh_user=True)
        with transaction.atomic():
            service = (
                Service.objects.select_for_update()
                .filter(
                    pk=pk,
                    domain=scope.domain,
                    team_id=scope.team_id,
                    deleted_at__isnull=True,
                )
                .first()
            )
            if service is None:
                return Response(status=status.HTTP_404_NOT_FOUND)
            service.status = Service.Status.DISABLED
            service.updated_by = scope.username
            service.updated_by_domain = scope.domain
            service.save(update_fields=("status", "updated_by", "updated_by_domain", "updated_at"))
        return Response(self.get_serializer(service).data)


class CatalogViewSet(viewsets.ReadOnlyModelViewSet):
    http_method_names = ["get", "head", "options"]
    serializer_class = CatalogServiceSerializer
    pagination_class = ITSMPagination
    queryset = Service.objects.none()

    @staticmethod
    def _published_queryset(scope):
        ready_current_version = ServiceVersion.objects.filter(
            service_id=OuterRef("pk"),
            version=OuterRef("current_version"),
            publish_status=ServiceVersion.PublishStatus.READY,
        )
        return (
            Service.objects.filter(
                domain=scope.domain,
                team_id=scope.team_id,
                status=Service.Status.PUBLISHED,
                current_version__gt=0,
                deleted_at__isnull=True,
            )
            .alias(has_ready_current_version=Exists(ready_current_version))
            .filter(has_ready_current_version=True)
        )

    @staticmethod
    def _attach_current_versions(services) -> None:
        service_list = list(services)
        version_filter = Q(pk__isnull=True)
        for service in service_list:
            version_filter |= Q(service_id=service.id, version=service.current_version)
        versions = ServiceVersion.objects.filter(
            version_filter,
            publish_status=ServiceVersion.PublishStatus.READY,
        )
        versions_by_service = {version.service_id: version for version in versions}
        for service in service_list:
            service.current_published_version = versions_by_service.get(service.id)

    @HasPermission("catalog-View")
    def list(self, request, *args, **kwargs):
        scope = request_scope(request)
        queryset = self._published_queryset(scope).order_by("name", "id")
        search = str(request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(name__icontains=search[:120])
        page = self.paginate_queryset(queryset)
        self._attach_current_versions(page)
        visible = [service for service in page if service.current_published_version is not None]
        return self.get_paginated_response(self.get_serializer(visible, many=True).data)

    @HasPermission("catalog-View")
    def retrieve(self, request, *args, **kwargs):
        scope = request_scope(request)
        service = get_object_or_404(
            self._published_queryset(scope),
            pk=kwargs["pk"],
        )
        self._attach_current_versions([service])
        if service.current_published_version is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(self.get_serializer(service).data)


class TicketViewSet(viewsets.GenericViewSet):
    http_method_names = ["get", "post", "head", "options"]
    serializer_class = TicketSerializer
    pagination_class = ITSMPagination
    queryset = Ticket.objects.none()

    @HasPermission("ticket-View")
    def list(self, request, *args, **kwargs):
        scope = request_scope(request)
        queryset = (
            Ticket.objects.filter(
                domain=scope.domain,
                team_id=scope.team_id,
                requester_user_id=scope.user_id,
            )
            .select_related("service", "service_version")
            .prefetch_related("audit_events")
        )
        status_filter = str(request.query_params.get("status") or "").strip()
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        search = str(request.query_params.get("search") or "").strip()[:120]
        if search:
            queryset = queryset.filter(Q(number__icontains=search) | Q(service__name__icontains=search))
        page = self.paginate_queryset(queryset.order_by("-created_at"))
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    @HasPermission("ticket-View,todo-View")
    def retrieve(self, request, *args, **kwargs):
        scope = request_scope(request)
        assigned_to_actor = TaskProjection.objects.filter(
            ticket_id=OuterRef("pk"),
            domain=scope.domain,
            team_id=scope.team_id,
            assignee_user_id=scope.user_id,
        )
        ticket = get_object_or_404(
            Ticket.objects.select_related("service", "service_version")
            .prefetch_related("audit_events")
            .alias(has_actor_task=Exists(assigned_to_actor))
            .filter(Q(requester_user_id=scope.user_id) | Q(has_actor_task=True)),
            pk=kwargs["pk"],
            domain=scope.domain,
            team_id=scope.team_id,
        )
        return Response(self.get_serializer(ticket).data)

    @HasPermission("ticket-Add")
    def create(self, request, *args, **kwargs):
        scope = request_scope(request, refresh_user=True)
        serializer = TicketCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            ticket, created = submit_ticket(
                **serializer.validated_data,
                user_id=scope.user_id,
                username=scope.username,
                domain=scope.domain,
                team_id=scope.team_id,
            )
        except TicketConflict as error:
            return Response({"detail": str(error), "code": "IDEMPOTENCY_CONFLICT"}, status=status.HTTP_409_CONFLICT)
        except ITSMValidationError as error:
            raise ValidationError({"detail": str(error)}) from error
        response_status = status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK
        return Response(self.get_serializer(ticket).data, status=response_status)

    @action(methods=["POST"], detail=True)
    @HasPermission("ticket-Close")
    def close(self, request, pk=None):
        scope = request_scope(request, refresh_user=True)
        with transaction.atomic():
            ticket = (
                Ticket.objects.select_for_update()
                .select_related("service", "service_version")
                .filter(
                    pk=pk,
                    domain=scope.domain,
                    team_id=scope.team_id,
                    requester_user_id=scope.user_id,
                )
                .first()
            )
            if ticket is None:
                return Response(status=status.HTTP_404_NOT_FOUND)
            if ticket.status == Ticket.Status.CLOSED:
                return Response(self.get_serializer(ticket).data)
            if ticket.status != Ticket.Status.WAITING_CONFIRMATION:
                return Response(
                    {"detail": "仅待确认工单可由提单人关闭", "code": "TICKET_NOT_CONFIRMABLE"},
                    status=status.HTTP_409_CONFLICT,
                )
            ticket.status = Ticket.Status.CLOSED
            ticket.closed_at = timezone.now()
            ticket.save(update_fields=("status", "closed_at", "updated_at"))
            AuditEvent.objects.get_or_create(
                ticket=ticket,
                action="REQUESTER_CONFIRMED",
                defaults={
                    "actor_user_id": scope.user_id,
                    "actor_username": scope.username,
                    "actor_domain": scope.domain,
                    "from_status": Ticket.Status.WAITING_CONFIRMATION,
                    "to_status": Ticket.Status.CLOSED,
                },
            )
        return Response(self.get_serializer(ticket).data)


class TaskViewSet(viewsets.GenericViewSet):
    http_method_names = ["get", "post", "head", "options"]
    serializer_class = TaskProjectionSerializer
    pagination_class = ITSMPagination
    queryset = TaskProjection.objects.none()

    @HasPermission("todo-View,ticket-View")
    def list(self, request, *args, **kwargs):
        scope = request_scope(request)
        queryset = TaskProjection.objects.filter(
            domain=scope.domain,
            team_id=scope.team_id,
            assignee_user_id=scope.user_id,
            status__in=(TaskProjection.Status.PENDING, TaskProjection.Status.SUBMITTING),
        ).select_related("ticket__service", "ticket__service_version")
        task_type = str(request.query_params.get("task_type") or "").strip()
        if task_type in (TaskProjection.Type.APPROVAL, TaskProjection.Type.HANDLING):
            queryset = queryset.filter(task_type=task_type)
        ticket_id = str(request.query_params.get("ticket_id") or "").strip()[:64]
        if ticket_id:
            queryset = queryset.filter(ticket_id=ticket_id)
        search = str(request.query_params.get("search") or "").strip()[:120]
        if search:
            queryset = queryset.filter(
                Q(ticket__number__icontains=search)
                | Q(ticket__service__name__icontains=search)
                | Q(title__icontains=search)
            )
        page = self.paginate_queryset(queryset.order_by("-created_at"))
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    @action(methods=["POST"], detail=True)
    @HasPermission("todo-Act")
    def act(self, request, pk=None):
        scope = request_scope(request, refresh_user=True)
        serializer = TaskActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = enqueue_task_action(
                pk,
                **serializer.validated_data,
                actor_user_id=scope.user_id,
                actor_username=scope.username,
                domain=scope.domain,
                team_id=scope.team_id,
            )
        except TaskProjection.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        except TaskActionConflict as error:
            return Response({"detail": str(error), "code": "TASK_ACTION_CONFLICT"}, status=status.HTTP_409_CONFLICT)
        except TaskActionInvalid as error:
            raise ValidationError({"detail": str(error)}) from error
        response_status = status.HTTP_200_OK if result.planned else status.HTTP_202_ACCEPTED
        return Response(
            {
                "command_id": str(result.command.id),
                "status": result.command.status,
                "planned": result.planned,
            },
            status=response_status,
        )
