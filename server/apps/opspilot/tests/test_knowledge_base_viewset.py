"""KnowledgeBaseViewSet：检索计数、创建默认值、改 embedding 触发重训、删除守卫。"""
import json
import uuid
from unittest.mock import patch

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.opspilot.enum import DocumentStatus
from apps.opspilot.models import (
    EmbedProvider,
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeGraph,
    LLMModel,
    LLMSkill,
    ManualKnowledge,
    QAPairs,
)
from apps.opspilot.viewsets.knowledge_base_view import KnowledgeBaseViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()
MOD = "apps.opspilot.viewsets.knowledge_base_view"


def _su(name="kb-admin"):
    return UserFactory(
        username=f"{name}-{uuid.uuid4().hex[:8]}",
        domain="domain.com",
        roles=[],
        is_superuser=True,
        group_list=[{"id": 1, "name": "T1"}],
    )


def _dispatch(action_name, method, *, data=None, query="", user=None, pk=None):
    path = f"/{query}"
    if method in ("post", "put", "patch"):
        request = getattr(factory, method)(path, data=data or {}, format="json")
    elif method == "delete":
        request = factory.delete(path)
    else:
        request = factory.get(path)
    user = user or _su()
    force_authenticate(request, user=user)
    request.COOKIES["current_team"] = "1"
    view = KnowledgeBaseViewSet.as_view({method: action_name})
    if pk is not None:
        return view(request, pk=pk)
    return view(request)


def _body(resp):
    if hasattr(resp, "data") and resp.data is not None and not isinstance(resp.data, (bytes, str)):
        try:
            return resp.data
        except Exception:
            pass
    return json.loads(resp.content.decode("utf-8"))


def test_retrieve_includes_document_counts():
    kb = KnowledgeBase.objects.create(name="kb-count", team=[1])
    doc = KnowledgeDocument.objects.create(knowledge_base=kb, name="d1", knowledge_source_type="manual")
    ManualKnowledge.objects.create(knowledge_document=doc, content="手册")
    QAPairs.objects.create(knowledge_base=kb, name="qa", document_id=0)
    resp = _dispatch("retrieve", "get", pk=kb.id)
    body = _body(resp)
    assert body["result"] is True
    data = body["data"]
    assert data["manual_count"] == 1
    assert data["qa_count"] == 1
    assert data["document_count"] == 1
    assert data["graph_count"] == 0


def test_create_uses_default_embed_and_rejects_duplicate_name():
    embed, _ = EmbedProvider.objects.get_or_create(name="FastEmbed(BAAI/bge-small-zh-v1.5)", defaults={"model": "bge"})
    kb_name = f"kb-new-{uuid.uuid4().hex[:8]}"
    with patch(f"{MOD}.log_operation"):
        resp = _dispatch("create", "post", data={"name": kb_name, "team": [1]})
    assert resp.status_code == 201
    obj = KnowledgeBase.objects.get(name=kb_name)
    assert obj.embed_model_id == embed.id
    assert obj.search_type == "mmr"
    assert obj.score_threshold == 0.3
    assert obj.enable_rerank is False

    dup = _dispatch("create", "post", data={"name": kb_name, "team": [1]})
    assert _body(dup)["result"] is False


def test_update_blocks_embed_change_while_training_and_queues_retrain():
    embed_a = EmbedProvider.objects.create(name="emb-a", model="a")
    embed_b = EmbedProvider.objects.create(name="emb-b", model="b")
    kb = KnowledgeBase.objects.create(name="kb-retrain", team=[1], embed_model=embed_a)
    KnowledgeDocument.objects.create(
        knowledge_base=kb, name="training", knowledge_source_type="file", train_status=DocumentStatus.TRAINING
    )
    view = KnowledgeBaseViewSet()
    view.loader = None
    user = _su("kb-retrain")
    req = factory.put(f"/{kb.id}/", {"name": "kb-retrain", "embed_model": embed_b.id, "team": [1]}, format="json")
    force_authenticate(req, user=user)
    req.COOKIES["current_team"] = "1"
    resp = KnowledgeBaseViewSet.as_view({"put": "update"})(req, pk=kb.id)
    assert _body(resp)["result"] is False

    KnowledgeDocument.objects.filter(knowledge_base=kb).update(train_status=DocumentStatus.READY)
    req2 = factory.put(f"/{kb.id}/", {"name": "kb-retrain", "embed_model": embed_b.id, "team": [1]}, format="json")
    force_authenticate(req2, user=user)
    req2.COOKIES["current_team"] = "1"
    with patch(f"{MOD}.retrain_all") as task, patch(f"{MOD}.log_operation"):
        ok = KnowledgeBaseViewSet.as_view({"put": "update"})(req2, pk=kb.id)
    assert ok.status_code == 200
    task.delay.assert_called_once()
    assert task.delay.call_args.args[0] == kb.id


def test_update_settings_renames_and_rejects_collision():
    kb = KnowledgeBase.objects.create(name="kb-set", team=[1])
    KnowledgeBase.objects.create(name="taken", team=[1])
    user = _su("kb-set")
    data = {
        "name": "taken",
        "enable_rerank": False,
        "enable_naive_rag": True,
        "enable_qa_rag": True,
        "enable_graph_rag": False,
        "rag_size": 10,
        "qa_size": 10,
        "graph_size": 5,
        "search_type": "mmr",
        "score_threshold": 0.4,
        "rerank_model": None,
    }
    req = factory.post(f"/{kb.id}/update_settings/", data, format="json")
    force_authenticate(req, user=user)
    req.COOKIES["current_team"] = "1"
    view = KnowledgeBaseViewSet.as_view({"post": "update_settings"})
    collide = view(req, pk=kb.id)
    assert _body(collide)["result"] is False

    data["name"] = "kb-renamed"
    data["introduction"] = "简介"
    req2 = factory.post(f"/{kb.id}/update_settings/", data, format="json")
    force_authenticate(req2, user=user)
    req2.COOKIES["current_team"] = "1"
    ok = view(req2, pk=kb.id)
    assert _body(ok)["result"] is True
    kb.refresh_from_db()
    assert kb.name == "kb-renamed"
    assert kb.enable_rerank is False
    assert kb.score_threshold == 0.4


def test_destroy_blocked_when_skill_uses_kb_and_cleans_related_on_success():
    kb = KnowledgeBase.objects.create(name="kb-del", team=[1])
    skill = LLMSkill.objects.create(name="uses-kb", team=[1])
    skill.knowledge_base.add(kb)
    resp = _dispatch("destroy", "delete", pk=kb.id)
    assert _body(resp)["result"] is False
    assert KnowledgeBase.objects.filter(id=kb.id).exists()

    skill.knowledge_base.clear()
    KnowledgeDocument.objects.create(knowledge_base=kb, name="d", knowledge_source_type="file")
    QAPairs.objects.create(knowledge_base=kb, name="qa", document_id=0)
    llm = LLMModel.objects.create(name="g-llm", model="gpt")
    KnowledgeGraph.objects.create(knowledge_base=kb, llm_model=llm, status="completed")
    with (
        patch(f"{MOD}.KnowledgeSearchService.delete_es_content"),
        patch(f"{MOD}.ChunkHelper.delete_es_content"),
        patch(f"{MOD}.GraphUtils.delete_graph") as del_graph,
        patch(f"{MOD}.log_operation"),
    ):
        ok = _dispatch("destroy", "delete", pk=kb.id)
    assert ok.status_code == 204
    del_graph.assert_called_once()
    assert not KnowledgeBase.objects.filter(id=kb.id).exists()


def test_get_teams_returns_user_group_list():
    user = _su("kb-teams")
    user.group_list = [{"id": 1, "name": "T1"}, {"id": 2, "name": "T2"}]
    user.save()
    resp = _dispatch("get_teams", "get", user=user)
    body = _body(resp)
    assert body["result"] is True
    assert body["data"] == user.group_list
