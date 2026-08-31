"""RAGService.format_naive_rag_kwargs：naive/qa 拆分；LLMViewSet.toggle_pin 切换。"""
import json
import uuid

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.opspilot.models import EmbedProvider, KnowledgeBase, KnowledgeDocument, LLMSkill, ModelVendor, UserPin
from apps.opspilot.services.rag_service import RAGService
from apps.opspilot.viewsets.llm_view import LLMViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()


def _vendor():
    return ModelVendor.objects.create(
        name=f"v-{uuid.uuid4().hex[:6]}",
        api_base="http://embed.local",
        api_key="ek",
        team=[1],
    )


def test_format_naive_rag_kwargs_splits_naive_and_qa():
    vendor = _vendor()
    embed = EmbedProvider.objects.create(name="emb", vendor=vendor, model="bge", team=[1])
    kb = KnowledgeBase.objects.create(
        name="kb-rag",
        team=[1],
        embed_model=embed,
        enable_naive_rag=True,
        enable_qa_rag=True,
        enable_graph_rag=False,
        rag_size=12,
        qa_size=4,
    )
    doc = KnowledgeDocument.objects.create(knowledge_base=kb, name="d1", knowledge_source_type="file")
    reqs, km, doc_map = RAGService.format_naive_rag_kwargs(
        {
            "rag_score_threshold": [{"knowledge_base": kb.id, "score": 0.42}],
            "enable_km_route": False,
            "km_llm_model": None,
        }
    )
    assert km == {}
    assert doc_map[doc.id]["name"] == "d1"
    assert [r["enable_naive_rag"] for r in reqs] == [True, False]
    assert [r["enable_qa_rag"] for r in reqs] == [False, True]
    assert reqs[0]["score_threshold"] == 0.42
    assert reqs[0]["index_name"] == f"knowledge_base_{kb.id}"
    assert reqs[0]["embed_model_name"] == "bge"


def test_toggle_pin_creates_then_deletes():
    user = UserFactory(
        username=f"pin-{uuid.uuid4().hex[:8]}",
        domain="domain.com",
        roles=[],
        is_superuser=True,
        group_list=[{"id": 1, "name": "T1"}],
    )
    skill = LLMSkill.objects.create(name="skill-pin", team=[1])
    view = LLMViewSet.as_view({"post": "toggle_pin"})

    def _call():
        request = factory.post("/")
        force_authenticate(request, user=user)
        request.COOKIES["current_team"] = "1"
        return view(request, pk=skill.id)

    first = json.loads(_call().content.decode())
    assert first["result"] is True
    assert first["data"]["is_pinned"] is True
    assert UserPin.objects.filter(username=user.username, object_id=skill.id, content_type="skill").exists()
    second = json.loads(_call().content.decode())
    assert second["data"]["is_pinned"] is False
    assert not UserPin.objects.filter(username=user.username, object_id=skill.id, content_type="skill").exists()
