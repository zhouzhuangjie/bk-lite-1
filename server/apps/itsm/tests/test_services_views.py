import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.itsm.models import Command, Service, ServiceVersion
from apps.itsm.views import ServiceViewSet


def schema():
    return {
        "type": "object",
        "properties": {"summary": {"type": "string", "title": "摘要", "maxLength": 120}},
        "required": ["summary"],
        "additionalProperties": False,
    }


def workflow_config():
    return {
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


@pytest.fixture
def member(db):
    user = get_user_model().objects.create(
        id=11,
        username="service-admin",
        domain="example.com",
        group_list=[{"id": 7, "name": "研发部"}],
    )
    user.permission = {
        "itsm": {
            "service_management-View",
            "service_management-Add",
            "service_management-Edit",
            "service_management-Publish",
        }
    }
    get_user_model().objects.create(
        id=21,
        username="handler",
        domain="example.com",
        group_list=[{"id": 7, "name": "研发部"}],
    )
    return user


def request(method, path, user, data=None, *, team=7):
    factory = APIRequestFactory()
    value = getattr(factory, method)(path, data or {}, format="json")
    value.COOKIES["current_team"] = str(team)
    force_authenticate(value, user=user)
    return value


@pytest.mark.django_db
def test_create_derives_domain_and_team_from_authenticated_scope(member):
    create = ServiceViewSet.as_view({"post": "create"})

    response = create(
        request(
            "post",
            "/services/",
            member,
            {
                "name": "数据库申请",
                "description": "申请数据库",
                "team_id": 99,
                "domain": "attacker.example",
                "form_schema": schema(),
                "workflow_config": workflow_config(),
            },
        )
    )

    assert response.status_code == 201
    service = Service.objects.get()
    assert service.team_id == 7
    assert service.domain == "example.com"
    assert service.created_by == "service-admin"
    assert "team_id" not in response.data or response.data["team_id"] == 7


@pytest.mark.django_db
def test_create_rejects_current_team_outside_membership(member):
    create = ServiceViewSet.as_view({"post": "create"})

    response = create(
        request(
            "post",
            "/services/",
            member,
            {"name": "越权服务", "form_schema": schema(), "workflow_config": workflow_config()},
            team=8,
        )
    )

    assert response.status_code == 403
    assert Service.objects.count() == 0


@pytest.mark.django_db
def test_list_filters_domain_and_team(member):
    common = {
        "description": "",
        "form_schema": schema(),
        "workflow_config": workflow_config(),
        "created_by": "seed",
        "updated_by": "seed",
    }
    visible = Service.objects.create(name="可见", domain="example.com", team_id=7, **common)
    Service.objects.create(name="其他组织", domain="example.com", team_id=8, **common)
    Service.objects.create(name="其他域", domain="other.example", team_id=7, **common)
    list_view = ServiceViewSet.as_view({"get": "list"})

    response = list_view(request("get", "/services/", member))

    assert response.status_code == 200
    assert [item["id"] for item in response.data["items"]] == [visible.id]


@pytest.mark.django_db
def test_update_uses_revision_and_publish_is_idempotent(member):
    service = Service.objects.create(
        name="数据库申请",
        domain="example.com",
        team_id=7,
        form_schema=schema(),
        workflow_config=workflow_config(),
        created_by="service-admin",
        updated_by="service-admin",
    )
    update = ServiceViewSet.as_view({"patch": "partial_update"})
    publish = ServiceViewSet.as_view({"post": "publish"})

    updated = update(
        request("patch", f"/services/{service.id}/", member, {"description": "新说明", "draft_revision": 0}),
        pk=service.id,
    )
    stale = update(
        request("patch", f"/services/{service.id}/", member, {"description": "旧写入", "draft_revision": 0}),
        pk=service.id,
    )
    first = publish(request("post", f"/services/{service.id}/publish/", member), pk=service.id)
    repeated = publish(request("post", f"/services/{service.id}/publish/", member), pk=service.id)

    assert updated.status_code == 200
    assert updated.data["draft_revision"] == 1
    assert stale.status_code == 409
    assert first.status_code == 202
    assert repeated.status_code == 202
    assert first.data["version"] == repeated.data["version"] == 1
    assert ServiceVersion.objects.filter(service=service).count() == 1
    assert Command.objects.filter(service_version__service=service).count() == 1


@pytest.mark.django_db
def test_publish_rejects_stale_or_cross_team_principal(member):
    config = workflow_config()
    config["handlerIds"] = [999]
    service = Service.objects.create(
        name="失效处理人服务",
        domain="example.com",
        team_id=7,
        form_schema=schema(),
        workflow_config=config,
        created_by=member.username,
        updated_by=member.username,
    )
    publish = ServiceViewSet.as_view({"post": "publish"})

    response = publish(request("post", f"/services/{service.id}/publish/", member), pk=service.id)

    assert response.status_code == 400
    assert ServiceVersion.objects.filter(service=service).count() == 0


@pytest.mark.django_db
def test_service_versions_are_scoped_and_published_service_can_be_disabled(member):
    service = Service.objects.create(
        name="可停用服务",
        domain="example.com",
        team_id=7,
        status=Service.Status.PUBLISHED,
        current_version=1,
        form_schema=schema(),
        workflow_config=workflow_config(),
        created_by=member.username,
        updated_by=member.username,
    )
    ServiceVersion.objects.create(
        service=service,
        version=1,
        source_revision=0,
        form_schema=service.form_schema,
        workflow_config=service.workflow_config,
        content_hash="a" * 64,
        publish_status=ServiceVersion.PublishStatus.READY,
        created_by=member.username,
        domain=member.domain,
    )
    versions = ServiceViewSet.as_view({"get": "versions"})
    disable = ServiceViewSet.as_view({"post": "disable"})

    listed = versions(request("get", f"/services/{service.id}/versions/", member), pk=service.id)
    stopped = disable(request("post", f"/services/{service.id}/disable/", member), pk=service.id)

    assert listed.status_code == 200
    assert listed.data["count"] == 1
    assert listed.data["items"][0]["version"] == 1
    assert stopped.status_code == 200
    service.refresh_from_db()
    assert service.status == Service.Status.DISABLED
