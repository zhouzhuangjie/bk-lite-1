"""LLMViewSet.update 剩余分支：密码占位保留、RAG 绑定与关闭清空。"""
import json
import uuid
from unittest.mock import patch

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.opspilot.models import KnowledgeBase, LLMSkill
from apps.opspilot.viewsets.llm_view import LLMFilter, LLMViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()
MOD = "apps.opspilot.viewsets.llm_view"


def _su(name="llm-upd"):
    return UserFactory(username=f"{name}-{uuid.uuid4().hex[:8]}", domain="domain.com", roles=[], is_superuser=True, group_list=[{"id": 1, "name": "T1"}])


def _body(resp):
    return json.loads(resp.content.decode("utf-8"))


def test_filter_skill_type_splits_or_passthrough():
    class Dummy:
        def __init__(self):
            self.kwargs = None

        def filter(self, **kwargs):
            self.kwargs = kwargs
            return "ok"

    dummy = Dummy()
    assert LLMFilter.filter_skill_type(dummy, "skill_type", "") is dummy
    assert LLMFilter.filter_skill_type(dummy, "skill_type", "1, 2,") == "ok"
    assert dummy.kwargs["skill_type__in"] == [1, 2]


def test_update_keeps_masked_password_and_binds_rag_then_clears():
    user = _su()
    kb = KnowledgeBase.objects.create(name="llm-kb", team=[1])
    skill = LLMSkill.objects.create(
        name="upd-skill",
        team=[1],
        skill_params=[{"key": "token", "type": "password", "value": "real-secret"}],
        enable_rag=True,
    )
    skill.knowledge_base.add(kb)
    data = {
        "name": "upd-skill",
        "team": [1],
        "skill_params": [{"key": "token", "type": "password", "value": "******"}],
        "tools": [{"kwargs": [{"type": "password", "value": "plain"}]}],
        "rag_score_threshold": [{"knowledge_base": kb.id, "score": 0.8}],
        "enable_rag": True,
        "created_by": "attacker",
    }
    req = factory.put(f"/{skill.id}/", data, format="json")
    force_authenticate(req, user=user)
    req.COOKIES["current_team"] = "1"
    with patch(f"{MOD}.log_operation"):
        resp = LLMViewSet.as_view({"put": "update"})(req, pk=skill.id)
    assert _body(resp)["result"] is True
    skill.refresh_from_db()
    assert skill.skill_params[0]["value"] == "real-secret"
    scores = list(skill.rag_score_threshold_map.values())
    assert scores == [0.8]
    assert list(skill.knowledge_base.values_list("id", flat=True)) == [kb.id]
    assert skill.created_by != "attacker" or skill.updated_by == user.username

    data["enable_rag"] = False
    req2 = factory.put(f"/{skill.id}/", data, format="json")
    force_authenticate(req2, user=user)
    req2.COOKIES["current_team"] = "1"
    with patch(f"{MOD}.log_operation"):
        LLMViewSet.as_view({"put": "update"})(req2, pk=skill.id)
    skill.refresh_from_db()
    assert skill.enable_rag is False
    assert skill.rag_score_threshold_map == {}
    assert skill.knowledge_base.count() == 0


def test_update_denies_non_owner():
    user = UserFactory(
        username=f"llm-guest-{uuid.uuid4().hex[:8]}",
        domain="domain.com",
        roles=[],
        is_superuser=False,
        group_list=[{"id": 1, "name": "T1"}],
    )
    user.permission = {"opspilot": {"skill_setting-Edit"}}
    skill = LLMSkill.objects.create(name="locked-upd", team=[1])
    req = factory.put(f"/{skill.id}/", {"name": "locked-upd", "team": [1]}, format="json")
    force_authenticate(req, user=user)
    req.COOKIES["current_team"] = "1"
    with patch.object(LLMViewSet, "get_has_permission", return_value=False):
        resp = LLMViewSet.as_view({"put": "update"})(req, pk=skill.id)
    assert _body(resp)["result"] is False
