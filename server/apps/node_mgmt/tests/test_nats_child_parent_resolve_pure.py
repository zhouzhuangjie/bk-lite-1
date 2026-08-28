"""NATS 子配置父级解析：按节点架构选精确匹配，歧义则失败。"""
import pytest

from apps.core.exceptions.base_app_exception import BaseAppException
from apps.node_mgmt.constants.node import NodeConstants
from apps.node_mgmt.nats.node import NatsService

pytestmark = pytest.mark.unit


def _item(node_id, collector, cfg_id, arch):
    return {
        "nodes__id": node_id,
        "collector__name": collector,
        "id": cfg_id,
        "collector__cpu_architecture": arch,
    }


def test_resolve_child_parent_config_prefers_exact_arm():
    rows = [
        _item("n1", "Telegraf", "x86", NodeConstants.X86_64_ARCH),
        _item("n1", "Telegraf", "arm", NodeConstants.ARM64_ARCH),
    ]
    assert NatsService._resolve_child_parent_config_id(rows, "n1", "Telegraf", "aarch64") == "arm"


def test_resolve_child_parent_config_x86_over_legacy():
    rows = [
        _item("n1", "Telegraf", "legacy", ""),
        _item("n1", "Telegraf", "x86", NodeConstants.X86_64_ARCH),
    ]
    assert NatsService._resolve_child_parent_config_id(rows, "n1", "Telegraf", "amd64") == "x86"


def test_resolve_child_parent_config_falls_back_to_legacy_x86():
    rows = [_item("n1", "Telegraf", "legacy", "")]
    assert NatsService._resolve_child_parent_config_id(rows, "n1", "Telegraf", "x86_64") == "legacy"


def test_resolve_child_parent_config_ambiguous_and_missing():
    rows = [
        _item("n1", "Telegraf", "a", NodeConstants.ARM64_ARCH),
        _item("n1", "Telegraf", "b", NodeConstants.ARM64_ARCH),
    ]
    with pytest.raises(BaseAppException, match="Ambiguous"):
        NatsService._resolve_child_parent_config_id(rows, "n1", "Telegraf", "arm64")
    with pytest.raises(BaseAppException, match="not found"):
        NatsService._resolve_child_parent_config_id([], "n1", "Telegraf", "x86_64")


def test_ensure_parent_configs_noop_when_empty():
    assert NatsService()._ensure_parent_configs_for_child_configs([]) is None


def test_encrypt_password_fields_skips_empty_and_encodes_secret():
    assert NatsService._encrypt_password_fields(None) is None
    assert NatsService._encrypt_password_fields({}) == {}
    out = NatsService._encrypt_password_fields({"NATS_PASSWORD": "plain", "HOST": "h"})
    assert out["HOST"] == "h"
    assert out["NATS_PASSWORD"] != "plain"


def test_merge_and_encrypt_keeps_unchanged_secret():
    assert NatsService._merge_and_encrypt_env_config({"p": "old"}, None) == {}
    merged = NatsService._merge_and_encrypt_env_config(
        {"NATS_PASSWORD": "enc-old"},
        {"NATS_PASSWORD": "enc-old", "HOST": "h"},
    )
    assert merged["NATS_PASSWORD"] == "enc-old"
    assert merged["HOST"] == "h"
    changed = NatsService._merge_and_encrypt_env_config({"NATS_PASSWORD": "enc-old"}, {"NATS_PASSWORD": "new-plain"})
    assert changed["NATS_PASSWORD"] != "new-plain"
    assert changed["NATS_PASSWORD"] != "enc-old"
