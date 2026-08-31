"""安装结果 schema：数值清洗、失败类型推断与动作归一。"""
from math import nan

import pytest

from apps.node_mgmt.utils import installer_schema as schema

pytestmark = pytest.mark.unit


def test_coerce_number_and_non_negative_int():
    assert schema._coerce_number(None) is None
    assert schema._coerce_number(True) is None
    assert schema._coerce_number("x") is None
    assert schema._coerce_number(nan) is None
    assert schema._coerce_number("3.5") == 3.5
    assert schema._coerce_non_negative_int(-2) == 0
    assert schema._coerce_non_negative_int("4") == 4
    assert schema._clean_text("  ") is None
    assert schema._clean_text(" hi ") == "hi"


def test_extract_target_path_and_failure_type():
    assert schema._extract_target_path("") is None
    assert schema._extract_target_path("open /opt/a.bin: text file busy") == "/opt/a.bin"
    assert schema._extract_target_path("/etc/x: permission denied") == "/etc/x"
    ctx = schema._extract_failure_context(
        {"package_file_key": "k", "storage_bucket": "b", "file_name": "p.tar.gz"},
        "open /opt/a.bin: text file busy",
        None,
    )
    assert ctx["file_key"] == "k"
    assert ctx["bucket"] == "b"
    assert ctx["package_name"] == "p.tar.gz"
    assert ctx["target_path"] == "/opt/a.bin"
    assert schema._infer_failure_type("text file busy", None, None) == "file_busy"
    assert schema._infer_failure_type("object not found", None, None) == "object_missing"
    assert schema._infer_failure_type("bucket xyz not found", None, None) == "bucket_missing"
    assert schema._infer_failure_type("authentication failed", None, None) == "auth"
    assert schema._infer_failure_type("connection refused", None, {"error_type": "connection"}) == "connection"
    assert schema._infer_failure_type("permission denied", None, None) == "permission"
    assert schema._infer_failure_type("no space left on device", None, None) == "disk"
    assert schema.normalize_installer_action(None) == "installer"
    assert schema.normalize_installer_action("download_package") == "download"
    assert schema.normalize_installer_status("SUCCESS") == "success"
    assert schema.normalize_installer_status("failed") == "error"
