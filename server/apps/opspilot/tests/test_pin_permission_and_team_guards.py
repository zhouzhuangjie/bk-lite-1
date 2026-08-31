"""PinMixin / CheckKnowledgePermission / TeamPermissionMixin 的权限与置顶契约。"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.http import JsonResponse
from rest_framework.exceptions import PermissionDenied

from apps.opspilot.utils.permission_check import CheckKnowledgePermission
from apps.opspilot.utils.pin_mixin import PinMixin
from apps.opspilot.utils.team_permission_mixin import TeamPermissionMixin

from django.db.models import QuerySet

from apps.opspilot.models import LLMSkill

pytestmark = pytest.mark.django_db


class _PinView(PinMixin):
    pin_content_type = "skill"
    loader = None

    def __init__(self):
        self.validated = []
        self.listed = []

    def _validate_current_team_permission(self, request):
        self.validated.append(True)
        return 1

    def get_queryset_by_permission(self, request, queryset):
        return queryset

    def _list(self, queryset):
        self.listed.append(queryset)
        return JsonResponse({"result": True, "ordered": True})

    def get_object(self):
        return SimpleNamespace(id=42)

    def get_has_permission(self, user, instance, current_team, include_children=False):
        return False


def test_query_by_groups_with_pinned_skips_validation_for_superuser_and_returns_non_queryset():
    view = _PinView()
    request = SimpleNamespace(user=SimpleNamespace(is_superuser=True, username="su", domain="d.com"))
    denied = JsonResponse({"result": False})
    view.get_queryset_by_permission = lambda req, qs: denied
    out = view.query_by_groups_with_pinned(request, queryset=MagicMock())
    assert out is denied
    assert view.validated == []

    view2 = _PinView()
    qs = LLMSkill.objects.none()
    with patch("apps.opspilot.utils.pin_mixin.UserPin.objects.filter") as filt:
        filt.return_value.values_list.return_value = [7, 8]
        resp = view2.query_by_groups_with_pinned(request, queryset=qs)
    assert json.loads(resp.content) == {"result": True, "ordered": True}
    assert len(view2.listed) == 1
    ordered = view2.listed[0]
    assert isinstance(ordered, QuerySet)
    assert ordered.query.order_by == ("-is_pinned_for_user", "-id")


def test_toggle_pin_returns_permission_error_for_non_superuser():
    view = _PinView()
    request = SimpleNamespace(
        user=SimpleNamespace(is_superuser=False, username="u", domain="d.com"),
        COOKIES={"include_children": "0"},
    )
    resp = view.toggle_pin(request, pk=42)
    body = json.loads(resp.content)
    assert body == {"result": False, "message": "You do not have permission to update this instance"}
    assert view.validated == [True]


def test_check_knowledge_permission_superuser_bypasses_and_team_denied():
    checker = CheckKnowledgePermission(model=SimpleNamespace())

    @checker
    def handler(request, pk=None):
        return "ok"

    su = SimpleNamespace(user=SimpleNamespace(is_superuser=True))
    assert handler(su) == "ok"

    denied = SimpleNamespace(
        user=SimpleNamespace(is_superuser=False, group_list=[{"id": 1}], locale="zh-Hans"),
        COOKIES={"current_team": "9"},
        GET=SimpleNamespace(dict=lambda: {}),
        data={},
    )
    with patch("apps.opspilot.utils.permission_check.LanguageLoader") as loader_cls:
        loader_cls.return_value.get.return_value = "无权访问该团队数据"
        with pytest.raises(PermissionDenied, match="无权访问该团队数据"):
            handler(denied)


def test_check_knowledge_permission_pk_insufficient_returns_403():
    kb = SimpleNamespace(id=3, team=[1])
    model = SimpleNamespace(objects=SimpleNamespace(get=lambda **kw: SimpleNamespace(knowledge_base=kb)))
    checker = CheckKnowledgePermission(model=model)

    @checker
    def handler(request, pk=None):
        return "ok"

    request = SimpleNamespace(
        user=SimpleNamespace(is_superuser=False, group_list=[{"id": 1}], locale="en"),
        COOKIES={"current_team": "1", "include_children": "0"},
        GET=SimpleNamespace(dict=lambda: {}),
        data={},
    )
    with patch.object(checker, "get_has_permission", return_value=False), patch(
        "apps.opspilot.utils.permission_check.LanguageLoader"
    ) as loader_cls:
        loader_cls.return_value.get.return_value = "insufficient permissions"
        resp = handler(request, pk=8)
    assert resp.status_code == 403
    assert json.loads(resp.content)["message"] == "insufficient permissions"


class _TeamView(TeamPermissionMixin):
    loader = None


def test_team_permission_mixin_cookie_bot_and_kb_guards():
    view = _TeamView()
    request = SimpleNamespace(
        user=SimpleNamespace(is_superuser=False, group_list=[{"id": 1}]),
        COOKIES={"current_team": "abc"},
    )
    with patch("apps.opspilot.utils.team_permission_mixin.get_current_team", return_value="abc"):
        assert view._parse_current_team_cookie(request) == 0
        with pytest.raises(PermissionDenied, match="无权访问该团队数据"):
            view._validate_current_team_permission(request)

    request.COOKIES["current_team"] = "1"
    with patch("apps.opspilot.utils.team_permission_mixin.get_current_team", return_value="1"):
        assert view._validate_current_team_permission(request) == 1
        request.user.group_list = [{"id": 2}]
        with pytest.raises(PermissionDenied, match="无权访问该团队数据"):
            view._validate_current_team_permission(request)

    request.user.group_list = [{"id": 1}]
    with patch("apps.opspilot.utils.team_permission_mixin.get_current_team", return_value="1"), patch(
        "apps.opspilot.utils.team_permission_mixin.Bot.objects.filter"
    ) as bot_filter:
        bot_filter.return_value.first.return_value = None
        with pytest.raises(PermissionDenied, match="Bot 不存在"):
            view._validate_bot_permission(request, 9)
        bot_filter.return_value.first.return_value = SimpleNamespace(team=[2])
        with pytest.raises(PermissionDenied, match="无权访问该 Bot 的数据"):
            view._validate_bot_permission(request, 9)

    with patch("apps.opspilot.utils.team_permission_mixin.get_current_team", return_value="1"), patch(
        "apps.opspilot.utils.team_permission_mixin.KnowledgeBase.objects.filter"
    ) as kb_filter:
        kb_filter.return_value.first.return_value = None
        with pytest.raises(PermissionDenied, match="知识库不存在"):
            view._validate_knowledge_base_permission(request, 3)
        kb_filter.return_value.first.return_value = SimpleNamespace(team=[2])
        with pytest.raises(PermissionDenied, match="无权访问该知识库"):
            view._validate_knowledge_base_permission(request, 3)
        kb = SimpleNamespace(team=[1])
        kb_filter.return_value.first.return_value = kb
        assert view._validate_knowledge_base_permission(request, 3) is kb
