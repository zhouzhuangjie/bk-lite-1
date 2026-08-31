"""MemoryEntity / BaseMemoryEngine 延迟加载与默认连接测试。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.opspilot.memory.engines.base import BaseMemoryEngine, MemoryEntity, MemoryReadResult, MemoryWriteResult

pytestmark = pytest.mark.unit


class _Engine(BaseMemoryEngine):
    def read(self, entity, query=None, top_k=5):
        return MemoryReadResult(context="c", source="t")

    def write(self, entity, content, title=None, metadata=None, model_id=None):
        return MemoryWriteResult(success=True, memory_id="m1")

    def delete(self, entity, memory_id=None):
        return True

    @classmethod
    def get_engine_info(cls):
        return {"type": "t", "name": "n", "description": "d"}

    @classmethod
    def get_config_schema(cls):
        return [{"name": "url", "required": True}]


def test_memory_entity_to_dict_omits_empty_fields():
    assert MemoryEntity().to_dict() == {}
    assert MemoryEntity(user_id="u1").to_dict() == {"user_id": "u1"}
    assert MemoryEntity(organization_id=7).to_dict() == {"organization_id": 7}
    assert MemoryEntity(user_id="u1", organization_id=7).to_dict() == {
        "user_id": "u1",
        "organization_id": 7,
    }


def test_memory_engine_lazy_space_config_and_default_connection():
    space = SimpleNamespace(get_decrypted_config=lambda: {"url": "http://m"})
    engine = _Engine(memory_space_id=11)
    with patch("apps.opspilot.models.MemorySpace.objects.get", return_value=space) as getter:
        assert engine.memory_space is space
        assert engine.memory_space is space
    getter.assert_called_once_with(id=11)
    assert engine.config == {"url": "http://m"}
    assert engine.config == {"url": "http://m"}
    assert engine.test_connection() == {"success": True, "message": "连接测试未实现"}
    assert engine.get_engine_info()["type"] == "t"
    assert engine.get_config_schema()[0]["name"] == "url"
