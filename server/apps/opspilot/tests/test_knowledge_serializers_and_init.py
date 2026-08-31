"""知识图谱/文档序列化校验与 ModelProviderInitService 模板初始化。"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from rest_framework.exceptions import ValidationError

from apps.opspilot.models import KnowledgeBase, KnowledgeDocument, KnowledgeGraph, LLMModel, LLMSkill, WebPageKnowledge
from apps.opspilot.serializers.knowledge_document_serializers import KnowledgeDocumentSerializer
from apps.opspilot.serializers.knowledge_graph_serializers import KnowledgeGraphSerializer
from apps.opspilot.services.model_provider_init_service import ModelProviderInitService
from apps.opspilot.services.skill_init_json import SKILL_LIST

pytestmark = pytest.mark.django_db


def _kb_llm():
    kb = KnowledgeBase.objects.create(name="kg-kb", team=[1])
    llm = LLMModel.objects.create(name="kg-llm", model="gpt", team=[1])
    return kb, llm


def test_knowledge_graph_create_rejects_duplicate_and_queues_task():
    kb, llm = _kb_llm()
    ser = KnowledgeGraphSerializer(
        data={"knowledge_base": kb.id, "llm_model": llm.id, "doc_list": [11]},
        context={"request": SimpleNamespace(user=SimpleNamespace(locale="en"))},
    )
    assert ser.is_valid(), ser.errors
    with patch("apps.opspilot.serializers.knowledge_graph_serializers.create_graph.delay") as delay:
        graph = ser.save()
    assert graph.status == "pending"
    assert graph.doc_list == [11]
    delay.assert_called_once_with(graph.id)

    dup = KnowledgeGraphSerializer(context={"request": SimpleNamespace(user=SimpleNamespace(locale="en"))})
    with pytest.raises(ValidationError) as exc:
        dup.create({"knowledge_base": kb, "llm_model": llm, "doc_list": []})
    assert "message" in exc.value.detail


def test_knowledge_graph_update_blocks_pending_and_queues_when_idle():
    kb, llm = _kb_llm()
    pending = KnowledgeGraph.objects.create(knowledge_base=kb, llm_model=llm, status="pending", doc_list=[1])
    ser = KnowledgeGraphSerializer(
        pending,
        data={"doc_list": [2]},
        partial=True,
        context={"request": SimpleNamespace(user=SimpleNamespace(locale="en"))},
    )
    assert ser.is_valid(), ser.errors
    with pytest.raises(ValidationError) as exc:
        ser.save()
    assert "message" in exc.value.detail

    idle_kb = KnowledgeBase.objects.create(name="kg-idle", team=[1])
    idle = KnowledgeGraph.objects.create(knowledge_base=idle_kb, llm_model=llm, status="completed", doc_list=[3])
    ser = KnowledgeGraphSerializer(
        idle,
        data={"doc_list": [4]},
        partial=True,
        context={"request": SimpleNamespace(user=SimpleNamespace(locale="en"))},
    )
    assert ser.is_valid(), ser.errors
    with patch("apps.opspilot.serializers.knowledge_graph_serializers.update_graph.delay") as delay:
        updated = ser.save()
    assert updated.status == "pending"
    delay.assert_called_once_with(idle.id, [3])


def test_knowledge_document_serializer_reads_web_page_sync_fields():
    kb = KnowledgeBase.objects.create(name="doc-kb", team=[1])
    file_doc = KnowledgeDocument.objects.create(knowledge_base=kb, name="file-doc", knowledge_source_type="file")
    web_doc = KnowledgeDocument.objects.create(knowledge_base=kb, name="web-doc", knowledge_source_type="web_page")
    run_at = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)
    WebPageKnowledge.objects.create(
        knowledge_document=web_doc,
        url="https://example.com/docs",
        sync_enabled=True,
        sync_time="02:30",
        last_run_time=run_at,
    )

    empty = KnowledgeDocumentSerializer()
    assert empty.web_page_doc_map == {}

    file_data = KnowledgeDocumentSerializer(file_doc).data
    assert file_data["sync_enabled"] is False
    assert file_data["sync_time"] == ""
    assert file_data["last_run_time"] == ""
    assert file_data["train_status_display"] == file_doc.get_train_status_display()

    web_data = KnowledgeDocumentSerializer(web_doc).data
    assert web_data["sync_enabled"] is True
    assert web_data["sync_time"] == "02:30"
    assert web_data["last_run_time"] == run_at

    many = KnowledgeDocumentSerializer([file_doc, web_doc], many=True).data
    by_name = {item["name"]: item for item in many}
    assert by_name["file-doc"]["sync_enabled"] is False
    assert by_name["web-doc"]["sync_enabled"] is True


def test_model_provider_init_service_replaces_template_skills():
    LLMSkill.objects.create(name="old-template", is_template=True, skill_type=2)
    LLMSkill.objects.create(name="keep-custom", is_template=False, skill_type=2)
    svc = ModelProviderInitService("alice")
    assert svc.owner == "alice"
    assert svc.group_id == 1
    assert ModelProviderInitService.get_group_id() == 1

    svc.init()
    assert not LLMSkill.objects.filter(name="old-template").exists()
    assert LLMSkill.objects.filter(name="keep-custom", is_template=False).exists()
    assert LLMSkill.objects.filter(is_template=True).count() == len(SKILL_LIST)
    assert LLMSkill.objects.filter(name=SKILL_LIST[0]["name"], is_template=True).exists()
