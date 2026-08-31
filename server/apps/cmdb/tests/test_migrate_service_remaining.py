"""ModelMigrate 剩余解析/公共选项库回填与旧实例组织修复。"""
import pytest

from apps.cmdb.constants.field_constraints import DEFAULT_NUMBER_CONSTRAINT, DEFAULT_TIME_CONSTRAINT, TimeDisplayFormat
from apps.cmdb.model_migrate import migrete_service
from apps.core.exceptions.base_app_exception import BaseAppException

pytestmark = pytest.mark.django_db


def _make(monkeypatch, model_config=None):
    monkeypatch.setattr(migrete_service.ModelMigrate, "get_model_config", lambda self: model_config or {})
    monkeypatch.setattr(migrete_service, "get_default_group_id", lambda: [1])
    return migrete_service.ModelMigrate(file_source=None, is_pre=True)


def test_parse_attr_option_int_time_enum_table(monkeypatch):
    m = _make(monkeypatch)
    number = m._parse_attr_option("int", "{'min': 1, 'max': 9.5}")
    assert number["min_value"] == 1
    assert number["max_value"] == 9.5
    assert m._parse_attr_option("time", "{'type': 'date'}") == {"display_format": TimeDisplayFormat.DATE}
    assert m._parse_attr_option("enum", "[{'id':'on','name':'开'}]") == [{"id": "on", "name": "开"}]
    table = m._parse_attr_option(
        "table",
        "[{'column_id':'c1','column_name':'列','column_type':'str','order':1}]",
    )
    assert table == [{"column_id": "c1", "column_name": "列", "column_type": "str", "order": 1}]
    assert m._parse_attr_option("int", "") == DEFAULT_NUMBER_CONSTRAINT
    assert m._parse_attr_option("time", "") == DEFAULT_TIME_CONSTRAINT


def test_normalize_enum_option_payload_public_library_fallback(monkeypatch):
    from apps.cmdb.models.public_enum_library import PublicEnumLibrary

    PublicEnumLibrary.objects.create(
        library_id="os_type",
        name="操作系统",
        team=[1],
        options=[{"id": "linux", "name": "Linux"}],
        created_by="system",
        updated_by="system",
    )
    m = _make(monkeypatch)
    option, meta = m._normalize_enum_option_payload(
        {"enum_rule_type": "public_library", "public_library_id": "os_type", "enum_select_mode": "single"},
        attr_id="os",
    )
    assert option == [{"id": "linux", "name": "Linux"}]
    assert meta == {
        "enum_rule_type": "public_library",
        "public_library_id": "os_type",
        "enum_select_mode": "single",
    }


def test_normalize_public_enum_options_and_team_errors(monkeypatch):
    m = _make(monkeypatch)
    with pytest.raises(BaseAppException, match="options 必须是数组"):
        m._normalize_public_enum_options({"id": "a"}, "ctx")
    with pytest.raises(BaseAppException, match="options\\[1\\] 必须是对象"):
        m._normalize_public_enum_options(["x"], "ctx")
    with pytest.raises(BaseAppException, match="options\\[1\\].id 不能为空"):
        m._normalize_public_enum_options([{"id": "", "name": "n"}], "ctx")
    with pytest.raises(BaseAppException, match="team 必须是数组"):
        m._normalize_team_value("{}", "ctx")
    with pytest.raises(BaseAppException, match="library_id 非法"):
        m._normalize_public_enum_library_row(
            {"library_id": "1bad", "name": "n", "team": "[]", "options": "[]"},
            3,
        )


def test_create_field_groups_skips_empty_and_groups_attrs(monkeypatch):
    from apps.cmdb.models.field_group import FieldGroup

    m = _make(monkeypatch)
    m._create_field_groups(
        [
            {"model_id": ""},
            {"model_id": "migrate_r13", "attrs": "not-json"},
            {
                "model_id": "migrate_r13",
                "attrs": '[{"attr_id":"name","attr_group":"基础"},{"attr_id":"ip","attr_group":"基础"},{"attr_id":"os"}]',
            },
        ]
    )
    groups = list(FieldGroup.objects.filter(model_id="migrate_r13").order_by("order"))
    assert [g.group_name for g in groups] == ["基础", "默认分组"]
    assert groups[0].attr_orders == ["name", "ip"]
    assert groups[1].attr_orders == ["os"]


def test_check_and_update_old_instances_organization(monkeypatch, fake_graph):
    m = _make(monkeypatch)
    fake = fake_graph(
        "apps.cmdb.model_migrate.migrete_service",
        query_entity=(
            [
                {"_id": 1, "organization": 8},
                {"_id": 2, "organization": []},
                {"_id": 3, "organization": [1]},
            ],
            3,
        ),
    )
    m.check_and_update_old_instances_organization()
    update_calls = [c for c in fake.calls if c[0] == "batch_update_node_properties"]
    assert update_calls
    kwargs = update_calls[0][2]
    assert kwargs["node_ids"] == [1, 2]
    assert kwargs["properties"]["organization"] == [1]
