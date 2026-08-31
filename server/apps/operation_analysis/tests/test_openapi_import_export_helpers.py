"""运营分析 Open API 导入导出：Token 鉴权、组织解析与按组织过滤 ID。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from rest_framework.exceptions import ValidationError

from apps.core.exceptions.base_app_exception import UnauthorizedException
from apps.operation_analysis.constants.import_export import ObjectType
from apps.operation_analysis.views.openapi_import_export_view import OpenImportExportViewSet

pytestmark = pytest.mark.unit


def test_check_api_auth_requires_api_pass():
    vs = OpenImportExportViewSet()
    vs._check_api_auth(SimpleNamespace(api_pass=True, path="/open"))
    with pytest.raises(UnauthorizedException, match="缺少有效的 API Token"):
        vs._check_api_auth(SimpleNamespace(api_pass=False, path="/open"))


def test_get_groups_from_request_accepts_int_str_and_dict():
    vs = OpenImportExportViewSet()
    assert vs._get_groups_from_request(SimpleNamespace(user=None)) == []
    assert vs._get_groups_from_request(SimpleNamespace(user=SimpleNamespace(group_list="1"))) == []
    assert vs._get_groups_from_request(
        SimpleNamespace(user=SimpleNamespace(group_list=[1, "2", {"id": 3}, {"id": "4"}, {"id": "x"}, "bad"]))
    ) == [1, 2, 3, 4]


def test_require_groups_and_username_fallback():
    vs = OpenImportExportViewSet()
    with pytest.raises(ValidationError, match="无法从API Token上下文解析有效的组织信息"):
        vs._require_groups(SimpleNamespace(user=SimpleNamespace(group_list=[])))
    req = SimpleNamespace(user=SimpleNamespace(group_list=[9]))
    assert vs._require_groups(req) == [9]

    anon = SimpleNamespace(user=SimpleNamespace(is_authenticated=False, username="u"))
    assert vs._get_username_from_request(anon) == "api_user"
    authed = SimpleNamespace(user=SimpleNamespace(is_authenticated=True, username="alice"))
    assert vs._get_username_from_request(authed) == "alice"


def test_filter_ids_by_org_dashboard_namespace_and_unknown():
    vs = OpenImportExportViewSet()
    dash_qs = MagicMock()
    dash_qs.filter.return_value = dash_qs
    dash_qs.values_list.return_value = [1, 3]
    ns_qs = MagicMock()
    ns_qs.filter.return_value = ns_qs
    ns_qs.values_list.return_value = [8]

    with (
        patch("apps.operation_analysis.models.models.Dashboard.objects") as dash_objects,
        patch("apps.operation_analysis.models.datasource_models.NameSpace.objects") as ns_objects,
    ):
        dash_objects.filter.return_value = dash_qs
        ns_objects.filter.return_value = ns_qs
        assert vs._filter_ids_by_org(ObjectType.DASHBOARD.value, [1, 2, 3], current_team=7) == [1, 3]
        dash_qs.filter.assert_called_with(groups__contains=7)
        assert vs._filter_ids_by_org(ObjectType.NAMESPACE.value, [8, 9]) == [8]
        assert vs._filter_ids_by_org("unknown-type", [1]) == []
