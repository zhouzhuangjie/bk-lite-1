"""运分审计日志：成功响应才记操作，导入结果按 status 映射动作文案。"""
from unittest.mock import MagicMock

import pytest
from rest_framework.response import Response

from apps.operation_analysis.common import audit_log

pytestmark = pytest.mark.unit


def test_get_response_name_reads_nested_or_top_level():
    assert audit_log.get_response_name(SimpleResponse({"name": "top"})) == "top"
    assert audit_log.get_response_name(SimpleResponse({"data": {"name": "nested"}})) == "nested"
    assert audit_log.get_response_name(SimpleResponse({"data": "x"}), fallback="fb") == "fb"


class SimpleResponse:
    def __init__(self, data):
        self.data = data


def test_is_success_response_requires_drf_2xx():
    assert audit_log._is_success_response(Response({"ok": True}, status=200)) is True
    assert audit_log._is_success_response(Response({"ok": False}, status=400)) is False
    assert audit_log._is_success_response({"status_code": 200}) is False


def test_log_ops_analysis_success_only_on_2xx(monkeypatch):
    calls = []
    monkeypatch.setattr(audit_log, "log_operation", lambda *args: calls.append(args))
    request = object()
    audit_log.log_ops_analysis_success(request, Response({}, status=201), "create", "新增仪表盘")
    audit_log.log_ops_analysis_success(request, Response({}, status=500), "create", "不应记录")
    assert len(calls) == 1
    assert calls[0][1] == "create"
    assert calls[0][2] == "ops-analysis"


def test_log_ops_analysis_import_results_maps_status_and_skips_unknown(monkeypatch):
    calls = []
    monkeypatch.setattr(audit_log, "log_operation", lambda *args: calls.append(args))
    audit_log.log_ops_analysis_import_results(
        object(),
        [
            {"status": "success", "object_type": "dashboard", "object_key": "d1"},
            {"status": "overwritten", "object_type": "datasource", "object_key": "s1"},
            {"status": "skipped", "object_type": "dashboard", "object_key": "d2"},
            "not-a-dict",
        ],
    )
    summaries = [c[3] for c in calls]
    assert summaries == ["导入新增仪表盘: d1", "导入更新数据源: s1"]
