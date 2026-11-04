import pytest

from apps.itsm.services.validation import ITSMValidationError, validate_form_schema, validate_submission, validate_workflow_config


def valid_schema():
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "title": "摘要", "maxLength": 120},
            "priority": {"type": "string", "title": "优先级", "enum": ["low", "high"], "x-widget": "radio"},
            "impact": {"type": "integer", "title": "影响范围", "minimum": 1, "maximum": 10},
        },
        "required": ["summary", "priority"],
        "additionalProperties": False,
    }


@pytest.mark.unit
def test_form_schema_accepts_supported_fields_and_submission():
    schema = valid_schema()

    validate_form_schema(schema)
    validate_submission(schema, {"summary": "数据库连接异常", "priority": "high", "impact": 3})


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda schema: schema.update({"$ref": "https://example.com/schema.json"}), "远程引用"),
        (lambda schema: schema["properties"].update({"nested": {"type": "object"}}), "字段类型"),
        (lambda schema: schema["properties"]["summary"].update({"x-widget": "javascript"}), "控件"),
        (lambda schema: schema.update({"additionalProperties": True}), "additionalProperties"),
    ],
)
def test_form_schema_rejects_unsafe_or_unsupported_contracts(mutate, message):
    schema = valid_schema()
    mutate(schema)

    with pytest.raises(ITSMValidationError, match=message):
        validate_form_schema(schema)


@pytest.mark.unit
def test_form_schema_rejects_unbounded_field_count():
    schema = valid_schema()
    schema["properties"] = {f"field_{index}": {"type": "string", "maxLength": 10} for index in range(51)}

    with pytest.raises(ITSMValidationError, match="字段数量"):
        validate_form_schema(schema)


@pytest.mark.unit
def test_submission_rejects_unknown_and_oversized_values():
    schema = valid_schema()

    with pytest.raises(ITSMValidationError, match="未定义字段"):
        validate_submission(schema, {"summary": "异常", "priority": "high", "debug": True})

    with pytest.raises(ITSMValidationError, match="摘要"):
        validate_submission(schema, {"summary": "x" * 121, "priority": "high"})


@pytest.mark.unit
def test_workflow_config_accepts_serial_and_parallel_stages():
    validate_workflow_config(
        {
            "schemaVersion": 1,
            "stages": [
                {
                    "key": "manager",
                    "name": "主管审批",
                    "mode": "serial",
                    "approverIds": [11, 12],
                    "allowBeforeSign": True,
                    "allowAfterSign": False,
                },
                {
                    "key": "security",
                    "name": "安全会签",
                    "mode": "parallel",
                    "approverIds": [21, 22],
                    "allowBeforeSign": False,
                    "allowAfterSign": True,
                },
            ],
            "handlerIds": [31],
        }
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "config",
    [
        {"schemaVersion": 1, "stages": [], "handlerIds": [31]},
        {
            "schemaVersion": 1,
            "stages": [{"key": "manager", "name": "主管", "mode": "or", "approverIds": [11]}],
            "handlerIds": [31],
        },
        {
            "schemaVersion": 1,
            "stages": [{"key": "manager", "name": "主管", "mode": "serial", "approverIds": [11, 11]}],
            "handlerIds": [31],
        },
        {
            "schemaVersion": 1,
            "stages": [{"key": "manager", "name": "主管", "mode": "serial", "approverIds": [11]}],
            "handlerIds": [],
        },
    ],
)
def test_workflow_config_rejects_unexecutable_definitions(config):
    with pytest.raises(ITSMValidationError):
        validate_workflow_config(config)
