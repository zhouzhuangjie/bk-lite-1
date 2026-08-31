"""AuthViewSet.update：超管删组织、无 cookie / 无权限拒绝、普通用户走 serializer。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from apps.core.utils.viewset_utils import AuthViewSet

pytestmark = pytest.mark.unit


def _vs(instance, *, permission_key="skill"):
    vs = AuthViewSet.__new__(AuthViewSet)
    vs.ORGANIZATION_FIELD = "team"
    vs.loader = None
    vs.permission_key = permission_key
    vs.get_object = lambda: instance
    vs.delete_rules = MagicMock()
    vs.value_error = lambda msg: Response({"result": False, "message": msg}, status=400)
    vs.get_has_permission = MagicMock(return_value=True)
    vs._validate_org_field_permission = MagicMock()
    vs.get_serializer = MagicMock()
    vs.perform_update = MagicMock()
    return vs


def test_update_superuser_deletes_removed_teams():
    instance = SimpleNamespace(id=9, team=[1, 2])
    vs = _vs(instance)
    request = SimpleNamespace(user=SimpleNamespace(is_superuser=True), data={"team": [1], "name": "n"})
    with patch.object(ModelViewSet, "update", return_value=Response({"ok": True})) as super_update:
        resp = vs.update(request)
    assert resp.data == {"ok": True}
    vs.delete_rules.assert_called_once_with(9, [2])
    super_update.assert_called_once()


def test_update_rejects_invalid_or_foreign_team():
    instance = SimpleNamespace(id=3, team=[1])
    vs = _vs(instance)
    vs._parse_current_team_cookie = lambda request, default=None: None
    request = SimpleNamespace(user=SimpleNamespace(is_superuser=False), data={"name": "n"}, COOKIES={})
    resp = vs.update(request)
    assert resp.status_code == 400
    assert "Invalid current_team" in resp.data["message"]

    vs._parse_current_team_cookie = lambda request, default=None: 99
    resp = vs.update(request)
    assert resp.status_code == 400
    assert "does not have permission" in resp.data["message"]


def test_update_non_superuser_validates_new_orgs_and_saves():
    instance = SimpleNamespace(id=4, team=[1], _prefetched_objects_cache={"x": 1})
    vs = _vs(instance)
    vs._parse_current_team_cookie = lambda request, default=None: 1
    serializer = MagicMock()
    serializer.data = {"id": 4, "team": [1, 2]}
    serializer.is_valid.return_value = True
    vs.get_serializer.return_value = serializer
    request = SimpleNamespace(
        user=SimpleNamespace(is_superuser=False),
        data={"team": [1, 2], "name": "n"},
        COOKIES={"include_children": "0"},
    )
    resp = vs.update(request)
    vs._validate_org_field_permission.assert_called_once()
    vs.delete_rules.assert_called_once_with(4, [])
    vs.perform_update.assert_called_once_with(serializer)
    assert resp.data["team"] == [1, 2]
    assert instance._prefetched_objects_cache == {}
