"""日志告警 all 列表、快照与事件原始数据：权限空集、可见告警、缺参/404。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework import status

from apps.log.models.collect_type import CollectType
from apps.log.tests.test_policy_alert_actions_views import _create_alert, _create_policy, _mock_policy_permission
from apps.log.views.policy import get_accessible_log_policy_ids

pytestmark = pytest.mark.django_db


def test_alert_list_all_empty_when_no_accessible_policies(api_client, authenticated_user, mocker):
    _mock_policy_permission(mocker, organization=1)
    api_client.cookies["current_team"] = "1"
    response = api_client.get("/api/v1/log/alert/all/")
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["result"] is True
    assert body["data"]["count"] == 0
    assert body["data"]["items"] == []


def test_alert_list_all_returns_only_permitted_alerts(api_client, authenticated_user, mocker):
    granted = _create_policy("alert-all-granted", organization=1)
    other = _create_policy("alert-all-other", organization=1)
    visible = _create_alert(granted, "alert-all-visible")
    _create_alert(other, "alert-all-hidden")
    _mock_policy_permission(mocker, policy_id=granted.id, organization=1)

    api_client.cookies["current_team"] = "1"
    response = api_client.get("/api/v1/log/alert/all/")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()["data"]
    assert data["count"] == 1
    assert [item["id"] for item in data["items"]] == [visible.id]
    assert data["items"][0]["policy"] == granted.id


def test_get_snapshots_missing_alert_returns_404(api_client, authenticated_user, mocker):
    _mock_policy_permission(mocker, organization=1)
    api_client.cookies["current_team"] = "1"
    response = api_client.get("/api/v1/log/alert/snapshots/missing-alert/")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "告警不存在" in response.json()["data"]


def test_get_snapshots_without_snapshot_returns_empty_list(api_client, authenticated_user, mocker):
    policy = _create_policy("snap-empty", organization=1)
    alert = _create_alert(policy, "alert-snap-empty")
    _mock_policy_permission(mocker, policy_id=policy.id, organization=1)
    api_client.cookies["current_team"] = "1"
    response = api_client.get(f"/api/v1/log/alert/snapshots/{alert.id}/")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()["data"]
    assert data["alert_info"]["id"] == alert.id
    assert data["alert_info"]["policy_id"] == policy.id
    assert data["snapshots"] == []


def test_get_snapshots_returns_loaded_payload(api_client, authenticated_user, mocker):
    policy = _create_policy("snap-ok", organization=1)
    alert = _create_alert(policy, "alert-snap-ok")
    payload = [{"type": "event", "event_id": "e1", "raw_data": {"msg": "hit"}}]
    snap = MagicMock()
    snap.snapshots = payload
    snap.created_at = timezone.now()
    snap.updated_at = timezone.now()
    mocker.patch("apps.log.models.policy.AlertSnapshot.objects.get", return_value=snap)
    _mock_policy_permission(mocker, policy_id=policy.id, organization=1)
    api_client.cookies["current_team"] = "1"
    response = api_client.get(f"/api/v1/log/alert/snapshots/{alert.id}/")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()["data"]
    assert data["alert_info"]["id"] == alert.id
    assert data["snapshots"] == payload
    assert data["snapshot_info"]["snapshot_count"] == 1


def test_rawdata_list_by_event_id_requires_event_id(api_client, authenticated_user, mocker):
    _mock_policy_permission(mocker, organization=1)
    api_client.cookies["current_team"] = "1"
    response = api_client.get("/api/v1/log/event_raw_data/by_event_id/")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "缺少事件ID" in response.json()["data"]


def test_rawdata_list_by_event_id_missing_and_found(api_client, authenticated_user, mocker):
    from apps.log.models.policy import EventRawData
    from apps.log.views.policy import EventRawDataViewSet

    policy = _create_policy("raw-ok", organization=1)
    _mock_policy_permission(mocker, policy_id=policy.id, organization=1)
    api_client.cookies["current_team"] = "1"

    qs = MagicMock()
    qs.get.side_effect = EventRawData.DoesNotExist
    mocker.patch.object(EventRawDataViewSet, "get_queryset", return_value=qs)

    missing = api_client.get("/api/v1/log/event_raw_data/by_event_id/?event_id=no-such")
    assert missing.status_code == status.HTTP_404_NOT_FOUND
    assert "未找到对应的原始数据" in missing.json()["data"]

    qs.get.side_effect = None
    qs.get.return_value = MagicMock()
    mocker.patch.object(
        EventRawDataViewSet,
        "get_serializer",
        return_value=SimpleNamespace(data={"data": {"message": "payload"}}),
    )
    found = api_client.get("/api/v1/log/event_raw_data/by_event_id/?event_id=event-raw-ok")
    assert found.status_code == status.HTTP_200_OK
    assert found.json()["data"]["data"]["message"] == "payload"
    qs.get.assert_called_with(event_id="event-raw-ok")


def test_accessible_log_policy_ids_global_excludes_typed_collect():
    typed = CollectType.objects.create(name=f"filebeat-global-{uuid4().hex[:8]}", collector="filebeat", icon="i")
    global_policy = _create_policy(f"global-only-{uuid4().hex[:8]}", organization=1, collect_type=None)
    typed_policy = _create_policy(f"typed-only-{uuid4().hex[:8]}", organization=1, collect_type=typed)
    request = SimpleNamespace(user=SimpleNamespace(username="u"), COOKIES={})
    perms = {
        "data": {
            "None": {"instance": [{"id": global_policy.id, "permission": ["View"]}]},
            str(typed.id): {"instance": [{"id": typed_policy.id, "permission": ["View"]}]},
        },
        "team": [1],
    }
    with (
        patch("apps.log.views.policy.get_current_team", return_value=1),
        patch("apps.log.views.policy.get_permissions_rules", return_value=perms),
    ):
        global_ids = get_accessible_log_policy_ids(request, collect_type_id="global")
        typed_ids = get_accessible_log_policy_ids(request, collect_type_id=str(typed.id))
    assert global_ids == [global_policy.id]
    assert typed_ids == [typed_policy.id]
    assert typed_policy.id not in global_ids
    assert global_policy.id not in typed_ids
