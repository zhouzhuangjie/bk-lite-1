import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.itsm.models import Command, Service, ServiceVersion, Ticket
from apps.itsm.views import CatalogViewSet, TicketViewSet


@pytest.fixture
def requester(db):
    user = get_user_model().objects.create(
        username="alice",
        domain="example.com",
        group_list=[{"id": 7, "name": "研发部"}],
    )
    user.permission = {"itsm": {"ticket-View", "ticket-Add", "ticket-Close"}}
    return user


@pytest.fixture
def published_service(db):
    form_schema = {
        "type": "object",
        "properties": {"summary": {"type": "string", "title": "摘要", "maxLength": 120}},
        "required": ["summary"],
        "additionalProperties": False,
    }
    workflow_config = {
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
    }
    service = Service.objects.create(
        name="数据库申请",
        domain="example.com",
        team_id=7,
        status=Service.Status.PUBLISHED,
        current_version=1,
        form_schema=form_schema,
        workflow_config=workflow_config,
        created_by="admin",
        updated_by="admin",
    )
    ServiceVersion.objects.create(
        service=service,
        version=1,
        source_revision=0,
        form_schema=form_schema,
        workflow_config=workflow_config,
        content_hash="a" * 64,
        publish_status=ServiceVersion.PublishStatus.READY,
        engine_deployment_id="deployment-1",
        engine_process_definition_id="itsm_service_1_v1:1:99",
        created_by="admin",
        domain="example.com",
    )
    return service


def request(method, path, user, data=None, *, team=7):
    factory = APIRequestFactory()
    value = getattr(factory, method)(path, data or {}, format="json")
    value.COOKIES["current_team"] = str(team)
    force_authenticate(value, user=user)
    return value


@pytest.mark.django_db
def test_submit_ticket_uses_frozen_version_and_authenticated_requester(requester, published_service):
    create = TicketViewSet.as_view({"post": "create"})

    response = create(
        request(
            "post",
            "/tickets/",
            requester,
            {
                "service_id": published_service.id,
                "request_key": "request-001",
                "form_data": {"summary": "需要生产数据库"},
                "requester_user_id": 999,
            },
        )
    )

    assert response.status_code == 202
    ticket = Ticket.objects.get()
    assert ticket.requester_user_id == requester.id
    assert ticket.service_version.version == 1
    assert ticket.status == Ticket.Status.SUBMITTING
    command = Command.objects.get(ticket=ticket)
    assert command.command_type == Command.Type.START_TICKET
    assert command.request_payload["process_definition_id"] == "itsm_service_1_v1:1:99"


@pytest.mark.django_db
def test_submit_ticket_is_idempotent_and_conflicting_payload_is_rejected(requester, published_service):
    create = TicketViewSet.as_view({"post": "create"})
    first_payload = {
        "service_id": published_service.id,
        "request_key": "request-001",
        "form_data": {"summary": "需要生产数据库"},
    }

    first = create(request("post", "/tickets/", requester, first_payload))
    repeated = create(request("post", "/tickets/", requester, first_payload))
    conflict = create(
        request(
            "post",
            "/tickets/",
            requester,
            {**first_payload, "form_data": {"summary": "不同内容"}},
        )
    )

    assert first.status_code == 202
    assert repeated.status_code == 200
    assert repeated.data["id"] == first.data["id"]
    assert conflict.status_code == 409
    assert Ticket.objects.count() == 1
    assert Command.objects.count() == 1


@pytest.mark.django_db
def test_submit_rejects_invalid_form_and_cross_team_service(requester, published_service):
    create = TicketViewSet.as_view({"post": "create"})

    invalid = create(
        request(
            "post",
            "/tickets/",
            requester,
            {"service_id": published_service.id, "request_key": "request-invalid", "form_data": {}},
        )
    )
    cross_team = create(
        request(
            "post",
            "/tickets/",
            requester,
            {"service_id": published_service.id, "request_key": "request-team", "form_data": {"summary": "正常"}},
            team=8,
        )
    )

    assert invalid.status_code == 400
    assert cross_team.status_code == 403
    assert Ticket.objects.count() == 0


@pytest.mark.django_db
def test_my_ticket_list_does_not_expose_other_requesters(requester, published_service):
    version = published_service.versions.get(version=1)
    own = Ticket.objects.create(
        number="ITSM-OWN",
        service=published_service,
        service_version=version,
        domain="example.com",
        team_id=7,
        requester_user_id=requester.id,
        requester_username="alice",
        request_key="own",
        request_fingerprint="a" * 64,
        form_data={"summary": "我的"},
    )
    Ticket.objects.create(
        number="ITSM-OTHER",
        service=published_service,
        service_version=version,
        domain="example.com",
        team_id=7,
        requester_user_id=999,
        requester_username="other",
        request_key="other",
        request_fingerprint="b" * 64,
        form_data={"summary": "别人的"},
    )
    list_view = TicketViewSet.as_view({"get": "list"})

    response = list_view(request("get", "/tickets/", requester))

    assert response.status_code == 200
    assert [item["id"] for item in response.data["items"]] == [str(own.id)]


@pytest.mark.django_db
def test_catalog_exposes_only_frozen_published_schema(requester, published_service):
    requester.permission["itsm"].add("catalog-View")
    published_service.form_schema = {
        "type": "object",
        "properties": {"draft_only": {"type": "string", "title": "草稿字段", "maxLength": 20}},
        "required": [],
        "additionalProperties": False,
    }
    published_service.save(update_fields=("form_schema", "updated_at"))
    list_view = CatalogViewSet.as_view({"get": "list"})

    response = list_view(request("get", "/catalog/", requester))

    assert response.status_code == 200
    assert len(response.data["items"]) == 1
    assert "summary" in response.data["items"][0]["form_schema"]["properties"]
    assert "draft_only" not in response.data["items"][0]["form_schema"]["properties"]


@pytest.mark.django_db
def test_catalog_count_excludes_service_without_ready_current_version(requester, published_service):
    requester.permission["itsm"].add("catalog-View")
    hidden = Service.objects.create(
        name="尚未就绪",
        domain="example.com",
        team_id=7,
        status=Service.Status.PUBLISHED,
        current_version=1,
        form_schema=published_service.form_schema,
        workflow_config=published_service.workflow_config,
        created_by="admin",
        updated_by="admin",
    )
    ServiceVersion.objects.create(
        service=hidden,
        version=1,
        source_revision=0,
        form_schema=hidden.form_schema,
        workflow_config=hidden.workflow_config,
        content_hash="f" * 64,
        publish_status=ServiceVersion.PublishStatus.FAILED,
        created_by="admin",
        domain="example.com",
    )
    list_view = CatalogViewSet.as_view({"get": "list"})

    response = list_view(request("get", "/catalog/", requester))

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert [item["id"] for item in response.data["items"]] == [published_service.id]


@pytest.mark.django_db
def test_requester_can_close_waiting_confirmation_ticket_idempotently(requester, published_service):
    version = published_service.versions.get(version=1)
    ticket = Ticket.objects.create(
        number="ITSM-CONFIRM",
        service=published_service,
        service_version=version,
        domain="example.com",
        team_id=7,
        requester_user_id=requester.id,
        requester_username=requester.username,
        request_key="confirm",
        request_fingerprint="c" * 64,
        form_data={"summary": "待确认"},
        status=Ticket.Status.WAITING_CONFIRMATION,
    )
    close = TicketViewSet.as_view({"post": "close"})

    first = close(request("post", f"/tickets/{ticket.id}/close/", requester), pk=ticket.id)
    repeated = close(request("post", f"/tickets/{ticket.id}/close/", requester), pk=ticket.id)

    ticket.refresh_from_db()
    assert first.status_code == 200
    assert repeated.status_code == 200
    assert ticket.status == Ticket.Status.CLOSED
    assert ticket.closed_at is not None
    assert ticket.audit_events.filter(action="REQUESTER_CONFIRMED").count() == 1


@pytest.mark.django_db
def test_ticket_cannot_be_closed_early_or_by_another_requester(requester, published_service):
    version = published_service.versions.get(version=1)
    ticket = Ticket.objects.create(
        number="ITSM-NOT-CLOSABLE",
        service=published_service,
        service_version=version,
        domain="example.com",
        team_id=7,
        requester_user_id=requester.id,
        requester_username=requester.username,
        request_key="not-closable",
        request_fingerprint="d" * 64,
        form_data={"summary": "审批中"},
        status=Ticket.Status.APPROVING,
    )
    other = get_user_model().objects.create(
        username="bob",
        domain="example.com",
        group_list=[{"id": 7, "name": "研发部"}],
    )
    other.permission = {"itsm": {"ticket-Close"}}
    close = TicketViewSet.as_view({"post": "close"})

    early = close(request("post", f"/tickets/{ticket.id}/close/", requester), pk=ticket.id)
    ticket.status = Ticket.Status.WAITING_CONFIRMATION
    ticket.save(update_fields=("status",))
    forbidden = close(request("post", f"/tickets/{ticket.id}/close/", other), pk=ticket.id)

    assert early.status_code == 409
    assert forbidden.status_code == 404
    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.WAITING_CONFIRMATION
