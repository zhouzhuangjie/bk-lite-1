"""ChildConfigViewSet：queryset 分流、collector_config 不可改、销毁授权失败。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.core.utils.web_utils import WebUtils
from apps.node_mgmt.views.child_config import ChildConfigViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()
VIEWS = "apps.node_mgmt.views.child_config"


def _actor():
    return UserFactory(is_superuser=True, domain="domain.com", group_list=[{"id": 1}])


def test_get_queryset_uses_mutable_for_write_actions():
    vs = ChildConfigViewSet()
    vs.action = "list"
    vs.request = SimpleNamespace()
    with (
        patch(f"{VIEWS}.get_authorized_child_config_queryset", return_value="auth-qs") as auth,
        patch(f"{VIEWS}.get_mutable_child_config_queryset", return_value="mut-qs") as mut,
    ):
        assert vs.get_queryset() == "auth-qs"
        vs.action = "destroy"
        assert vs.get_queryset() == "mut-qs"
    auth.assert_called_once()
    mut.assert_called_once()


def test_update_rejects_collector_config_change_and_destroy_authorization_error():
    actor = _actor()
    vs = ChildConfigViewSet()
    instance = SimpleNamespace(collector_config_id=1, _prefetched_objects_cache=None)
    vs.get_object = lambda: instance
    vs.get_serializer = lambda inst, data, partial: SimpleNamespace(
        is_valid=lambda raise_exception=False: True,
        validated_data={"collector_config": SimpleNamespace(id=2)},
        data={"id": 1},
    )
    request = SimpleNamespace(data={}, user=actor)
    resp = vs._update(request, partial=False)
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.data == {"result": False, "message": "collector_config cannot be modified"}

    denied = WebUtils.response_403("no")
    with patch(f"{VIEWS}.authorize_mutable_child_config_ids", return_value=(None, denied)):
        request = factory.delete("/x/")
        force_authenticate(request, user=actor)
        request.COOKIES["current_team"] = "1"
        resp = ChildConfigViewSet.as_view({"delete": "destroy"})(request, pk=9)
    assert resp.status_code == 403
