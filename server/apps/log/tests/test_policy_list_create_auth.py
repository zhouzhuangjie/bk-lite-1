"""PolicyViewSet：列表分页、创建组织校验、操作鉴权 403。"""
import pytest
from rest_framework import status

from apps.log.models.policy import Policy, PolicyOrganization


def _mock_rules(mocker, team, data=None):
    mocker.patch(
        "apps.log.views.policy.get_permissions_rules",
        return_value={"data": data or {}, "team": team},
    )


def _create_policy(name, organization):
    policy = Policy.objects.create(
        name=name,
        alert_type="keyword",
        alert_name=name,
        alert_level="warning",
        alert_condition={"query": "error"},
        schedule={"type": "min", "value": 5},
        period={"type": "min", "value": 5},
    )
    PolicyOrganization.objects.create(policy=policy, organization=organization)
    return policy


def _payload(**overrides):
    data = {
        "name": "policy-create-r13",
        "alert_type": "keyword",
        "alert_name": "alert",
        "alert_level": "warning",
        "alert_condition": {"query": "error"},
        "schedule": {"type": "min", "value": 5},
        "period": {"type": "min", "value": 5},
        "organizations": [1],
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
def test_list_paginates_accessible_policies(api_client, mocker):
    first = _create_policy("policy-page-a", 1)
    second = _create_policy("policy-page-b", 1)
    _create_policy("policy-page-c", 1)
    _mock_rules(mocker, team=[1])
    api_client.cookies["current_team"] = "1"
    response = api_client.get("/api/v1/log/policy/?page=1&page_size=2")
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["result"] is True
    assert body["data"]["count"] == 3
    assert len(body["data"]["items"]) == 2
    returned_ids = {item["id"] for item in body["data"]["items"]}
    assert returned_ids.issubset({first.id, second.id, Policy.objects.get(name="policy-page-c").id})
    assert all(item["permission"] == ["View", "Operate"] for item in body["data"]["items"])


@pytest.mark.django_db
def test_create_rejects_invalid_organizations_payload(api_client, mocker):
    _mock_rules(mocker, team=[1])
    api_client.cookies["current_team"] = "1"

    not_list = api_client.post("/api/v1/log/policy/", data=_payload(organizations="1"), format="json")
    assert not_list.status_code == status.HTTP_400_BAD_REQUEST
    assert not_list.json()["message"] == "organizations must be a list"

    not_int = api_client.post("/api/v1/log/policy/", data=_payload(organizations=[True]), format="json")
    assert not_int.json()["message"] == "organizations entries must be integers"

    required = api_client.post("/api/v1/log/policy/", data=_payload(organizations=[]), format="json")
    assert required.status_code == status.HTTP_400_BAD_REQUEST
    assert required.json()["result"] is False
    assert required.json()["data"] == "organizations is required"
    assert required.json()["message"] == ""


@pytest.mark.django_db
def test_create_forbids_organizations_outside_scope(api_client, mocker):
    _mock_rules(mocker, team=[1])
    api_client.cookies["current_team"] = "1"
    response = api_client.post("/api/v1/log/policy/", data=_payload(organizations=[2]), format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json()["message"] == "User does not have permission to assign policies to these organizations"


@pytest.mark.django_db
def test_create_persists_organizations_in_scope(api_client, mocker):
    _mock_rules(mocker, team=[1])
    api_client.cookies["current_team"] = "1"
    response = api_client.post("/api/v1/log/policy/", data=_payload(), format="json")
    assert response.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED)
    policy = Policy.objects.get(name="policy-create-r13")
    assert list(policy.policyorganization_set.values_list("organization", flat=True)) == [1]


@pytest.mark.django_db
def test_update_and_destroy_forbid_without_operate(api_client, mocker):
    policy = _create_policy("policy-auth-403", 1)
    _mock_rules(
        mocker,
        team=[1],
        data={"None": {"instance": [{"id": policy.id, "permission": ["View"]}]}},
    )
    api_client.cookies["current_team"] = "1"
    update = api_client.put(
        f"/api/v1/log/policy/{policy.id}/",
        data=_payload(name="policy-auth-403"),
        format="json",
    )
    assert update.status_code == status.HTTP_403_FORBIDDEN
    assert update.json()["message"] == "User does not have permission to operate this policy"

    destroy = api_client.delete(f"/api/v1/log/policy/{policy.id}/")
    assert destroy.status_code == status.HTTP_403_FORBIDDEN
    assert destroy.json()["message"] == "User does not have permission to operate this policy"
    assert Policy.objects.filter(id=policy.id).exists()
