"""ImportExportAuthorizationService 剩余鉴权：团队校验、冲突决策、提交权限。"""
from types import SimpleNamespace

import pytest
from rest_framework.exceptions import PermissionDenied

from apps.operation_analysis.constants.import_export import (
    ConflictAction,
    ConflictReason,
    ImportExportErrorCode,
    ObjectType,
)
from apps.operation_analysis.models.models import Dashboard
from apps.operation_analysis.services.import_export.authorization_service import ImportExportAuthorizationService

AUTH = ImportExportAuthorizationService


def _request(user, include_children="0"):
    return SimpleNamespace(user=user, COOKIES={"include_children": include_children})


def test_get_request_permissions_dict_set_and_other():
    req = _request(SimpleNamespace(permission={"ops-analysis": {"view-View"}}))
    assert AUTH.get_request_permissions(req) == {"view-View"}
    req = _request(SimpleNamespace(permission={"view-AddChart"}))
    assert AUTH.get_request_permissions(req) == {"view-AddChart"}
    req = _request(SimpleNamespace(permission=["x"]))
    assert AUTH.get_request_permissions(req) == set()


def test_has_permission_superuser_bypasses_and_normal_checks_set():
    super_req = _request(SimpleNamespace(is_superuser=True, permission=set()))
    assert AUTH.has_permission(super_req, "view-View") is True
    normal = _request(SimpleNamespace(is_superuser=False, permission={"view-View"}))
    assert AUTH.has_permission(normal, "view-View") is True
    assert AUTH.has_permission(normal, "view-EditChart") is False


def test_validate_current_team_contracts():
    super_req = _request(SimpleNamespace(is_superuser=True, group_list=[]))
    assert AUTH.validate_current_team(super_req, 9) == 9

    normal = _request(SimpleNamespace(is_superuser=False, group_list=[{"id": 1}]))
    with pytest.raises(PermissionDenied, match="无权访问该团队数据"):
        AUTH.validate_current_team(normal, None)
    with pytest.raises(PermissionDenied, match="无权访问该团队数据"):
        AUTH.validate_current_team(normal, 2)
    assert AUTH.validate_current_team(normal, 1) == 1


def test_normalize_ids_accepts_dict_string_and_int():
    assert AUTH._normalize_ids("1") == set()
    assert AUTH._normalize_ids([{"id": 3}, "4", 5, "x", None]) == {3, 4, 5}


def test_validate_conflict_decisions_rejects_disallowed_action():
    conflicts = [
        {"object_key": "dash::a", "object_type": "dashboard", "suggested_actions": ["overwrite", "skip"]},
        {"object_key": "dash::b", "object_type": "dashboard", "suggested_actions": []},
    ]
    errors = AUTH.validate_conflict_decisions(conflicts, {"dash::a": "rename"})
    assert errors == [
        {
            "code": ImportExportErrorCode.IMPORT_PERMISSION_DENIED,
            "message": "对象 'dash::a' 不允许执行冲突动作 rename",
            "object_key": "dash::a",
            "object_type": "dashboard",
            "allowed_actions": ["overwrite", "skip"],
        }
    ]


@pytest.mark.django_db
def test_can_access_existing_object_org_scope_and_instance_rule(authenticated_user, monkeypatch):
    dash = Dashboard.objects.create(name="auth-r13", groups=[1], created_by=authenticated_user.username)
    authenticated_user.is_superuser = False
    req = _request(authenticated_user)
    assert AUTH.can_access_existing_object(req, ObjectType.DASHBOARD, dash, 2) is False

    monkeypatch.setattr(AUTH, "_get_permission_data", classmethod(lambda cls, *a, **k: {"team": [1]}))
    assert AUTH.can_access_existing_object(req, ObjectType.DASHBOARD, dash, 1) is True

    monkeypatch.setattr(AUTH, "_get_permission_data", classmethod(lambda cls, *a, **k: {"instance": [dash.id]}))
    assert AUTH.can_access_existing_object(req, ObjectType.DASHBOARD, dash, 3) is False
    dash.groups = [3]
    dash.save(update_fields=["groups"])
    assert AUTH.can_access_existing_object(req, ObjectType.DASHBOARD, dash, 3) is True


@pytest.mark.django_db
def test_filter_ids_by_scope_allows_creator_and_builtin(authenticated_user, monkeypatch):
    authenticated_user.is_superuser = False
    req = _request(authenticated_user)
    mine = Dashboard.objects.create(name="auth-mine", groups=[1], created_by=authenticated_user.username)
    builtin = Dashboard.objects.create(name="auth-builtin", groups=[1], is_build_in=True, created_by="system")
    other = Dashboard.objects.create(name="auth-other", groups=[1], created_by="other")
    monkeypatch.setattr(AUTH, "_get_permission_data", classmethod(lambda cls, *a, **k: {}))
    allowed = AUTH._filter_ids_by_scope(req, ObjectType.DASHBOARD, [mine.id, builtin.id, other.id], 1)
    assert set(allowed) == {mine.id, builtin.id}


def test_get_export_group_ids_with_and_without_children(monkeypatch):
    req = _request(SimpleNamespace(group_tree=[]), include_children="0")
    assert AUTH._get_export_group_ids(req, None) == []
    assert AUTH._get_export_group_ids(req, 7) == [7]
    req.COOKIES["include_children"] = "1"
    monkeypatch.setattr(
        "apps.core.utils.viewset_utils.GenericViewSetFun.extract_child_group_ids",
        lambda tree, team: [7, 8],
    )
    assert AUTH._get_export_group_ids(req, 7) == [7, 8]


@pytest.mark.django_db
def test_validate_import_submit_permissions_denies_missing_create(authenticated_user, monkeypatch):
    authenticated_user.is_superuser = False
    authenticated_user.group_list = [{"id": 1}]
    authenticated_user.permission = set()
    req = _request(authenticated_user)
    item = SimpleNamespace(key="dashboard::new", name="new-dash")
    doc = SimpleNamespace(
        namespaces=[],
        datasources=[],
        dashboards=[item],
        topologies=[],
        architectures=[],
        screens=[],
        reports=[],
    )
    monkeypatch.setattr(AUTH, "get_existing_objects_batch", classmethod(lambda cls, *a, **k: {}))
    with pytest.raises(PermissionDenied) as exc:
        AUTH.validate_import_submit_permissions(req, doc, [], {}, 1)
    detail = exc.value.detail
    assert detail["success"] == "False"
    assert detail["message"] == "当前用户没有本次 YAML 导入所需的对象权限"
    assert detail["errors"][0]["code"] == ImportExportErrorCode.IMPORT_PERMISSION_DENIED
    assert "view-AddChart" in detail["errors"][0]["message"]


@pytest.mark.django_db
def test_apply_precheck_permissions_marks_no_permission_conflict(authenticated_user, monkeypatch):
    authenticated_user.is_superuser = False
    authenticated_user.group_list = [{"id": 1}]
    authenticated_user.permission = {"view-AddChart"}
    existing = Dashboard.objects.create(name="exist-r13", groups=[9], created_by="other")
    item = SimpleNamespace(key="dashboard::exist-r13", name="exist-r13")
    doc = SimpleNamespace(
        namespaces=[],
        datasources=[],
        dashboards=[item],
        topologies=[],
        architectures=[],
        screens=[],
        reports=[],
    )
    result = {
        "valid": True,
        "conflicts": [
            {
                "object_key": item.key,
                "object_type": "dashboard",
                "suggested_actions": [ConflictAction.OVERWRITE.value],
            }
        ],
        "errors": [],
    }
    req = _request(authenticated_user)
    monkeypatch.setattr(AUTH, "get_existing_objects_batch", classmethod(lambda cls, *a, **k: {item.name: existing}))
    out = AUTH.apply_precheck_permissions(req, doc, result, 1)
    assert out["conflicts"][0]["reason"] == ConflictReason.NO_PERMISSION_CONFLICT
    assert out["conflicts"][0]["suggested_actions"] == [ConflictAction.RENAME.value]
