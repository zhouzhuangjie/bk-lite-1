"""export_source_api_data：按启用状态过滤并写出 JSON。"""
import json

import pytest
from django.core.management import call_command

from apps.operation_analysis.models.datasource_models import DataSourceAPIModel

pytestmark = pytest.mark.django_db


def test_export_source_api_data_filters_active_and_writes_json(tmp_path):
    DataSourceAPIModel.objects.create(
        name="active-api",
        rest_api="/api/a",
        desc="A",
        params=[{"key": "q"}],
        is_active=True,
        groups=[1],
        created_by="ops",
    )
    DataSourceAPIModel.objects.create(
        name="inactive-api",
        rest_api="/api/b",
        desc="B",
        params=[],
        is_active=False,
        groups=[1],
        created_by="system",
    )
    out = tmp_path / "export.json"
    call_command("export_source_api_data", output=str(out), active_only=True, exclude_builtin=True)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload == [
        {"name": "active-api", "desc": "A", "rest_api": "/api/a", "params": [{"key": "q"}]}
    ]
