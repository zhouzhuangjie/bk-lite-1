from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from jsonschema import Draft202012Validator

MAX_FORM_FIELDS = 50
MAX_SCHEMA_BYTES = 64 * 1024
MAX_SUBMISSION_BYTES = 256 * 1024
MAX_ENUM_ITEMS = 100
MAX_APPROVAL_STAGES = 20
MAX_STAGE_APPROVERS = 20
MAX_HANDLERS = 1

SUPPORTED_FIELD_TYPES = {"string", "integer", "number", "boolean", "array"}
SUPPORTED_WIDGETS = {"input", "textarea", "number", "select", "radio", "multiselect", "switch", "checkbox"}
FIELD_KEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
STAGE_KEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


class ITSMValidationError(ValueError):
    """ITSM 配置或运行输入不满足受限契约。"""


def _json_size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError) as error:
        raise ITSMValidationError("内容必须是可序列化的 JSON") from error


def _reject_references(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in {"$ref", "$dynamicRef", "$recursiveRef"}:
                raise ITSMValidationError("表单 schema 不允许远程引用或本地引用")
            _reject_references(item)
    elif isinstance(value, list):
        for item in value:
            _reject_references(item)


def _validate_enum(field_key: str, field: Mapping[str, Any], *, array_items: Mapping[str, Any] | None = None) -> None:
    enum = (array_items or field).get("enum")
    if enum is None:
        return
    if not isinstance(enum, list) or not enum or len(enum) > MAX_ENUM_ITEMS:
        raise ITSMValidationError(f"字段 {field_key} 的候选项数量必须在 1 到 {MAX_ENUM_ITEMS} 之间")
    normalized = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in enum]
    if len(normalized) != len(set(normalized)):
        raise ITSMValidationError(f"字段 {field_key} 的候选项不能重复")


def _validate_field(field_key: str, field: Any) -> None:
    if not FIELD_KEY_PATTERN.fullmatch(field_key):
        raise ITSMValidationError(f"字段标识 {field_key} 非法")
    if not isinstance(field, Mapping):
        raise ITSMValidationError(f"字段 {field_key} 必须是 JSON 对象")

    field_type = field.get("type")
    if field_type not in SUPPORTED_FIELD_TYPES:
        raise ITSMValidationError(f"字段 {field_key} 的字段类型不受支持")
    title = field.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        raise ITSMValidationError(f"字段 {field_key} 必须设置 1 到 120 个字符的标题")

    widget = field.get("x-widget")
    if widget is not None and widget not in SUPPORTED_WIDGETS:
        raise ITSMValidationError(f"字段 {field_key} 的控件不受支持")

    if field_type == "array":
        items = field.get("items")
        if not isinstance(items, Mapping) or items.get("type") != "string":
            raise ITSMValidationError(f"字段 {field_key} 的数组只能包含字符串")
        _validate_enum(field_key, field, array_items=items)
        max_items = field.get("maxItems", MAX_ENUM_ITEMS)
        if isinstance(max_items, bool) or not isinstance(max_items, int) or not 1 <= max_items <= MAX_ENUM_ITEMS:
            raise ITSMValidationError(f"字段 {field_key} 的 maxItems 非法")
    else:
        if "items" in field:
            raise ITSMValidationError(f"字段 {field_key} 只有数组可以定义 items")
        _validate_enum(field_key, field)

    if field_type == "string":
        max_length = field.get("maxLength")
        if field.get("enum") is not None and max_length is None:
            return
        if isinstance(max_length, bool) or not isinstance(max_length, int) or not 1 <= max_length <= 10_000:
            raise ITSMValidationError(f"字段 {field_key} 必须设置 1 到 10000 的 maxLength")


def validate_form_schema(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict):
        raise ITSMValidationError("表单 schema 必须是 JSON 对象")
    if _json_size(schema) > MAX_SCHEMA_BYTES:
        raise ITSMValidationError("表单 schema 超过大小上限")
    _reject_references(schema)

    if schema.get("type") != "object":
        raise ITSMValidationError("表单 schema 顶层类型必须是 object")
    if schema.get("additionalProperties") is not False:
        raise ITSMValidationError("表单 schema 必须将 additionalProperties 设置为 false")

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise ITSMValidationError("表单 schema 必须包含 properties")
    if len(properties) > MAX_FORM_FIELDS:
        raise ITSMValidationError(f"表单字段数量不能超过 {MAX_FORM_FIELDS}")
    for field_key, field in properties.items():
        _validate_field(field_key, field)

    required = schema.get("required", [])
    if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
        raise ITSMValidationError("required 必须是字段标识数组")
    if len(required) != len(set(required)) or not set(required).issubset(properties):
        raise ITSMValidationError("required 包含重复或未定义字段")

    try:
        Draft202012Validator.check_schema(schema)
    except Exception as error:
        raise ITSMValidationError("表单 schema 不符合 JSON Schema 规范") from error
    return schema


def validate_submission(schema: dict[str, Any], payload: Any) -> dict[str, Any]:
    validate_form_schema(schema)
    if not isinstance(payload, dict):
        raise ITSMValidationError("提单数据必须是 JSON 对象")
    if _json_size(payload) > MAX_SUBMISSION_BYTES:
        raise ITSMValidationError("提单数据超过大小上限")

    unknown = sorted(set(payload) - set(schema["properties"]))
    if unknown:
        raise ITSMValidationError(f"提单数据包含未定义字段：{', '.join(unknown)}")

    errors = sorted(Draft202012Validator(schema).iter_errors(payload), key=lambda item: list(item.path))
    if errors:
        error = errors[0]
        field_key = str(next(iter(error.path), ""))
        field = schema["properties"].get(field_key, {})
        title = field.get("title") or field_key or "表单"
        raise ITSMValidationError(f"{title}：{error.message}")
    return payload


def _positive_unique_ids(value: Any, *, label: str, maximum: int) -> list[int]:
    if not isinstance(value, list) or not value or len(value) > maximum:
        raise ITSMValidationError(f"{label}数量必须在 1 到 {maximum} 之间")
    if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in value):
        raise ITSMValidationError(f"{label}必须使用有效用户 ID")
    if len(value) != len(set(value)):
        raise ITSMValidationError(f"{label}不能重复")
    return value


def validate_workflow_config(config: Any) -> dict[str, Any]:
    if not isinstance(config, dict) or config.get("schemaVersion") != 1:
        raise ITSMValidationError("流程配置版本不受支持")
    stages = config.get("stages")
    if not isinstance(stages, list) or not 1 <= len(stages) <= MAX_APPROVAL_STAGES:
        raise ITSMValidationError(f"审批阶段数量必须在 1 到 {MAX_APPROVAL_STAGES} 之间")

    stage_keys: set[str] = set()
    for index, stage in enumerate(stages, start=1):
        if not isinstance(stage, dict):
            raise ITSMValidationError(f"第 {index} 个审批阶段必须是 JSON 对象")
        key = stage.get("key")
        if not isinstance(key, str) or not STAGE_KEY_PATTERN.fullmatch(key) or key in stage_keys:
            raise ITSMValidationError(f"第 {index} 个审批阶段标识非法或重复")
        stage_keys.add(key)
        name = stage.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ITSMValidationError(f"第 {index} 个审批阶段名称非法")
        if stage.get("mode") not in {"serial", "parallel"}:
            raise ITSMValidationError(f"第 {index} 个审批阶段只支持串行或会签")
        _positive_unique_ids(stage.get("approverIds"), label=f"第 {index} 个审批阶段的审批人", maximum=MAX_STAGE_APPROVERS)
        for flag in ("allowBeforeSign", "allowAfterSign"):
            if not isinstance(stage.get(flag, False), bool):
                raise ITSMValidationError(f"第 {index} 个审批阶段的加签配置非法")

    _positive_unique_ids(config.get("handlerIds"), label="处理人", maximum=MAX_HANDLERS)
    return config
