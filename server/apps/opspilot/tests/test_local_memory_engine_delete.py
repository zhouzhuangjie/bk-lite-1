"""LocalMemoryEngine.delete：按 memory_id 或实体批量删除。"""
import pytest

from apps.opspilot.memory.engines.base import MemoryEntity
from apps.opspilot.memory.engines.local_engine import LocalMemoryEngine
from apps.opspilot.models import Memory, MemorySpace

pytestmark = pytest.mark.django_db


def _space():
    return MemorySpace.objects.create(name="mem-space", team=[1], scope=MemorySpace.SCOPE_TEAM)


def test_delete_by_memory_id_and_missing_id():
    space = _space()
    mem = Memory.objects.create(
        memory_space=space,
        title="t1",
        content="c1",
        owner_username="alice",
        owner_domain="domain.com",
    )
    engine = LocalMemoryEngine(space.id)
    assert engine.delete(MemoryEntity(user_id="alice@domain.com"), memory_id=str(mem.id)) is True
    assert Memory.objects.filter(id=mem.id).count() == 0
    assert engine.delete(MemoryEntity(user_id="alice@domain.com"), memory_id="999999") is False


def test_delete_all_for_user_and_org():
    space = _space()
    Memory.objects.create(
        memory_space=space, title="u", content="c", owner_username="bob", owner_domain="domain.com"
    )
    Memory.objects.create(
        memory_space=space,
        title="org",
        content="c",
        owner_username="team",
        owner_domain="",
        organization_id=7,
    )
    engine = LocalMemoryEngine(space.id)
    assert engine.delete(MemoryEntity(user_id="bob@domain.com")) is True
    assert Memory.objects.filter(owner_username="bob").count() == 0
    assert engine.delete(MemoryEntity(organization_id=7)) is True
    assert Memory.objects.filter(organization_id=7).count() == 0
