"""viewset_utils 剩余鉴权 / 规范化 / 列表契约。

补充既有 more/extra 未锁住的分支：
- GenericViewSetFun._get_app_name 非 apps 模块返回 None；
- get_has_permission 规则查询异常 -> False；
- filter_by_group include_children 且模型含组织字段时拼 Q；
- AuthViewSet._validate_current_team_permission 无效/越权团队；
- _normalize_org_values JSON 数组 / 逗号串 / None 跳过；
- get_detail / destroy 当前团队不在用户组 -> PermissionDenied；
- _list 分页响应与异常上抛；
- list / query_by_groups 异常上抛；
- _validate_name 空名与非法列表。
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.db.models import Q
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.core.utils.viewset_utils import (
    AuthViewSet,
    GenericViewSetFun,
    LanguageViewSet,
    MaintainerViewSet,
)

pytestmark = pytest.mark.unit


def _auth_vs(app_name="cmdb", permission_key=None, org_field="team"):
    vs = AuthViewSet.__new__(AuthViewSet)
    vs.ORGANIZATION_FIELD = org_field
    vs.loader = None
    vs.core_loader = None
    vs._get_app_name = lambda: app_name
    if permission_key is not None:
        vs.permission_key = permission_key
    return vs


class TestGetAppNameNone:
    def test_非apps模块返回None(self):
        class _Other(GenericViewSetFun):
            pass

        _Other.__module__ = "other.pkg.views"
        assert _Other()._get_app_name() is None


class TestGetHasPermissionException:
    def test_规则查询异常返回False(self):
        vs = GenericViewSetFun()
        vs.ORGANIZATION_FIELD = "team"
        vs.permission_key = "instance"
        vs._get_app_name = lambda: "core"
        user = SimpleNamespace(group_list=[1], group_tree=[])
        instance = SimpleNamespace(id=10, team=[1])
        with patch(
            "apps.core.utils.viewset_utils.get_permission_rules",
            side_effect=RuntimeError("rpc down"),
        ):
            assert vs.get_has_permission(user, instance, current_team=1) is False


class TestFilterByGroupOrgField:
    @pytest.mark.django_db
    def test_include_children拼组织Q(self):
        from apps.cmdb.models.collect_model import CollectModels

        user = SimpleNamespace(
            is_superuser=True,
            group_list=[{"id": 1}],
            group_tree=[{"id": 1, "subGroups": [{"id": 2}, {"id": 3}]}],
        )
        req = SimpleNamespace(user=user, COOKIES={"include_children": "1"})
        with patch("apps.core.utils.viewset_utils.get_current_team", return_value="1"):
            current_team, include_children, org_field, query = AuthViewSet.filter_by_group(
                CollectModels.objects.all(), req, user
            )
        assert current_team == 1
        assert include_children is True
        assert org_field == "team"
        assert len(query.children) == 3

    @pytest.mark.django_db
    def test_include_children无子组回退当前组(self):
        from apps.cmdb.models.collect_model import CollectModels

        user = SimpleNamespace(is_superuser=True, group_list=[{"id": 5}], group_tree=[])
        req = SimpleNamespace(user=user, COOKIES={"include_children": "1"})
        with patch("apps.core.utils.viewset_utils.get_current_team", return_value="5"):
            _, include_children, _, query = AuthViewSet.filter_by_group(
                CollectModels.objects.all(), req, user
            )
        assert include_children is True
        assert query.children == [("team__contains", 5)]


class TestValidateCurrentTeamPermission:
    def test_无效团队抛PermissionDenied(self):
        vs = _auth_vs()
        req = SimpleNamespace(user=SimpleNamespace(is_superuser=False, group_list=[]))
        with patch.object(vs, "_parse_current_team_cookie", return_value=0):
            with pytest.raises(PermissionDenied, match="无权访问该团队数据"):
                vs._validate_current_team_permission(req)

    def test_普通用户团队不在组内拒绝(self):
        vs = _auth_vs()
        req = SimpleNamespace(
            user=SimpleNamespace(is_superuser=False, group_list=[{"id": 1}])
        )
        with patch.object(vs, "_parse_current_team_cookie", return_value=9):
            with pytest.raises(PermissionDenied, match="无权访问该团队数据"):
                vs._validate_current_team_permission(req)

    def test_超管跳过组校验(self):
        vs = _auth_vs()
        req = SimpleNamespace(user=SimpleNamespace(is_superuser=True, group_list=[]))
        with patch.object(vs, "_parse_current_team_cookie", return_value=9):
            assert vs._validate_current_team_permission(req) == 9


class TestNormalizeOrgValuesRemaining:
    def test_json数组字符串(self):
        assert AuthViewSet._normalize_org_values({"team": "[1, 2, 3]"}, "team") == [1, 2, 3]

    def test_json数组含非法项跳过(self):
        assert AuthViewSet._normalize_org_values({"team": "[1, \"x\", 4]"}, "team") == [1, 4]

    def test_非法json回退单值失败(self):
        assert AuthViewSet._normalize_org_values({"team": "[not-json]"}, "team") == []

    def test_逗号分隔与空段(self):
        assert AuthViewSet._normalize_org_values({"team": "1, ,2,x"}, "team") == [1, 2]

    def test_None被跳过(self):
        assert AuthViewSet._normalize_org_values({"team": [None, 8]}, "team") == [8]


class TestDetailDestroyTeamDenied:
    def test_get_detail团队不在用户组(self):
        vs = _auth_vs(permission_key="probe")
        vs.get_object = lambda: SimpleNamespace(id=8, team=[1])
        request = SimpleNamespace(
            user=SimpleNamespace(is_superuser=False, group_list=[{"id": 2}]),
            COOKIES={},
        )
        with patch.object(vs, "_parse_current_team_cookie", return_value=1):
            with pytest.raises(PermissionDenied, match="无权访问该团队数据"):
                vs.get_detail(request)

    def test_destroy团队不在用户组(self):
        vs = _auth_vs(permission_key="probe")
        vs.get_object = lambda: SimpleNamespace(id=8, team=[1])
        request = SimpleNamespace(
            user=SimpleNamespace(is_superuser=False, group_list=[{"id": 2}]),
            COOKIES={},
        )
        with patch.object(vs, "_parse_current_team_cookie", return_value=1):
            with pytest.raises(PermissionDenied, match="无权访问该团队数据"):
                vs.destroy(request)


class TestListAndQueryExceptions:
    def test_list异常上抛(self):
        vs = _auth_vs()
        vs.filter_queryset = MagicMock(side_effect=RuntimeError("qs boom"))
        vs.get_queryset = MagicMock()
        with pytest.raises(RuntimeError, match="qs boom"):
            vs.list(SimpleNamespace())

    def test_query_by_groups异常上抛(self):
        vs = _auth_vs()
        vs.get_queryset_by_permission = MagicMock(side_effect=RuntimeError("perm boom"))
        with pytest.raises(RuntimeError, match="perm boom"):
            vs.query_by_groups(SimpleNamespace(), MagicMock())

    def test_list分页返回paginated(self):
        vs = _auth_vs()
        vs.paginate_queryset = MagicMock(return_value=[{"id": 1}])
        vs.get_serializer = MagicMock(return_value=SimpleNamespace(data=[{"id": 1}]))
        vs.get_paginated_response = MagicMock(return_value=Response({"count": 1, "results": [{"id": 1}]}))
        resp = vs._list(MagicMock())
        assert resp.data["count"] == 1
        vs.get_paginated_response.assert_called_once()

    def test_list无分页直接序列化(self):
        vs = _auth_vs()
        vs.paginate_queryset = MagicMock(return_value=None)
        vs.get_serializer = MagicMock(return_value=SimpleNamespace(data=[{"id": 2}]))
        resp = vs._list(MagicMock())
        assert resp.data == [{"id": 2}]

    def test_list内部异常上抛(self):
        vs = _auth_vs()
        vs.paginate_queryset = MagicMock(side_effect=RuntimeError("page boom"))
        with pytest.raises(RuntimeError, match="page boom"):
            vs._list(MagicMock())


class TestValidateNameGuards:
    def test_空名与非法列表返回空串(self):
        vs = _auth_vs()
        vs.queryset = MagicMock()
        assert vs._validate_name("", [{"id": 1, "name": "A"}], [1]) == ""
        assert vs._validate_name("n", "bad", [1]) == ""
        assert vs._validate_name("n", [{"id": 1, "name": "A"}], "bad") == ""


class TestMaintainerNoRequest:
    def test_perform_create无request走super(self):
        vs = MaintainerViewSet.__new__(MaintainerViewSet)
        serializer = SimpleNamespace(context={})
        with patch(
            "rest_framework.viewsets.ModelViewSet.perform_create", return_value="created"
        ) as super_create:
            assert vs.perform_create(serializer) == "created"
            super_create.assert_called_once_with(serializer)

    def test_perform_update无request走super(self):
        vs = MaintainerViewSet.__new__(MaintainerViewSet)
        serializer = SimpleNamespace(context={})
        with patch(
            "rest_framework.viewsets.ModelViewSet.perform_update", return_value="updated"
        ) as super_update:
            assert vs.perform_update(serializer) == "updated"
            super_update.assert_called_once_with(serializer)

    def test_perform_create异常上抛(self):
        vs = MaintainerViewSet.__new__(MaintainerViewSet)
        serializer = SimpleNamespace(context={"request": object()})
        with pytest.raises(AttributeError):
            vs.perform_create(serializer)

    def test_perform_update异常上抛(self):
        vs = MaintainerViewSet.__new__(MaintainerViewSet)
        serializer = SimpleNamespace(context={"request": object()})
        with pytest.raises(AttributeError):
            vs.perform_update(serializer)


class TestLanguageInitializeNoUser:
    def test_无user时locale为en(self):
        vs = LanguageViewSet.__new__(LanguageViewSet)
        vs._get_app_name = lambda: "core"
        raw = SimpleNamespace(user=None)
        with patch(
            "rest_framework.viewsets.ModelViewSet.initialize_request",
            return_value=raw,
        ), patch("apps.core.utils.viewset_utils.LanguageLoader") as loader_cls:
            out = vs.initialize_request(raw)
        loader_cls.assert_called_once_with(app="core", default_lang="en")
        assert out is raw
        assert vs.loader is loader_cls.return_value
