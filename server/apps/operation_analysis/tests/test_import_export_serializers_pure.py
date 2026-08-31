"""导入导出请求序列化：canvas/config 分流，空 YAML 拒绝。"""
import pytest
from rest_framework.exceptions import ValidationError

from apps.operation_analysis.constants.import_export import ObjectType, ScopeType
from apps.operation_analysis.serializers.import_export_serializers import (
    ExportRequestSerializer,
    ImportPrecheckRequestSerializer,
    ImportSubmitRequestSerializer,
)

pytestmark = pytest.mark.unit


def test_export_request_assigns_canvas_scope_for_dashboard():
    ser = ExportRequestSerializer(data={"object_type": ObjectType.DASHBOARD.value, "object_ids": [1, 2]})
    assert ser.is_valid(), ser.errors
    assert ser.validated_data["scope"] == ScopeType.CANVAS.value


def test_export_request_assigns_config_scope_for_datasource():
    ser = ExportRequestSerializer(data={"object_type": ObjectType.DATASOURCE.value, "object_ids": [3]})
    assert ser.is_valid(), ser.errors
    assert ser.validated_data["scope"] == ScopeType.CONFIG.value


def test_export_request_rejects_empty_ids():
    ser = ExportRequestSerializer(data={"object_type": ObjectType.DASHBOARD.value, "object_ids": []})
    assert ser.is_valid() is False
    assert "object_ids" in ser.errors


def test_precheck_rejects_blank_yaml():
    ser = ImportPrecheckRequestSerializer(data={"yaml_content": "   "})
    assert ser.is_valid() is False
    assert "yaml_content" in ser.errors


def test_submit_accepts_yaml_and_default_lists():
    ser = ImportSubmitRequestSerializer(data={"yaml_content": "kind: dashboard\n"})
    assert ser.is_valid(), ser.errors
    assert ser.validated_data["conflict_decisions"] == []
    assert ser.validated_data["secret_supplements"] == []


def test_submit_validates_conflict_decision_action():
    ser = ImportSubmitRequestSerializer(
        data={
            "yaml_content": "x: 1",
            "conflict_decisions": [{"object_key": "k", "action": "not-a-real-action"}],
        }
    )
    assert ser.is_valid() is False
    assert "conflict_decisions" in ser.errors
