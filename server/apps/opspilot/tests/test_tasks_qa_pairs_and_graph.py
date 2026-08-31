"""opspilot.tasks：QA 生成失败保留任务、图谱重建状态机、记忆客户端缺失。"""
from unittest.mock import MagicMock, patch

import pytest

from apps.opspilot import tasks
from apps.opspilot.enum import KnowledgeTaskStatus
from apps.opspilot.models import EmbedProvider, KnowledgeBase, KnowledgeGraph, KnowledgeTask, LLMModel, QAPairs

pytestmark = pytest.mark.django_db


def test_build_memory_write_client_returns_none_for_invalid_or_missing():
    assert tasks._build_memory_write_client(None) is None
    assert tasks._build_memory_write_client("not-int") is None
    assert tasks._build_memory_write_client(999999) is None


def test_create_qa_pairs_missing_list_and_failure_retains_task():
    assert tasks.create_qa_pairs([999999], only_question=True) is None
    embed = EmbedProvider.objects.create(name="qa-embed", model="e")
    kb = KnowledgeBase.objects.create(name="qa-kb", team=[1], embed_model=embed)
    llm = LLMModel.objects.create(name="qa-llm", model="gpt")
    qa = QAPairs.objects.create(
        knowledge_base=kb, name="qa-fail", document_id=1, llm_model=llm, answer_llm_model=llm
    )
    helper = MagicMock()
    helper.get_qa_content.side_effect = RuntimeError("es down")
    with patch("apps.opspilot.tasks.ChunkHelper", return_value=helper):
        tasks.create_qa_pairs([qa.id], only_question=True)
    qa.refresh_from_db()
    assert qa.status == "failed"
    task = KnowledgeTask.objects.get(knowledge_base_id=kb.id, is_qa_task=True)
    assert task.status == KnowledgeTaskStatus.FAILED


def test_create_qa_pairs_success_deletes_tracking_task():
    embed = EmbedProvider.objects.create(name="qa-embed-ok", model="e")
    kb = KnowledgeBase.objects.create(name="qa-ok", team=[1], embed_model=embed)
    llm = LLMModel.objects.create(name="qa-llm-ok", model="gpt")
    qa = QAPairs.objects.create(
        knowledge_base=kb, name="qa-ok", document_id=2, qa_count=1, llm_model=llm, answer_llm_model=llm
    )
    helper = MagicMock()
    helper.get_qa_content.return_value = [{"chunk_id": "c1", "content": "正文"}]
    helper.create_document_qa_pairs.return_value = 3
    with patch("apps.opspilot.tasks.ChunkHelper", return_value=helper), patch(
        "apps.opspilot.tasks.ChunkHelper.delete_es_content"
    ) as delete_es:
        tasks.create_qa_pairs([qa.id], only_question=False, delete_old_qa_pairs=True)
    qa.refresh_from_db()
    assert qa.status == "completed"
    assert qa.generate_count == 3
    delete_es.assert_called_once_with(qa.id)
    assert not KnowledgeTask.objects.filter(knowledge_base_id=kb.id, is_qa_task=True).exists()


def test_get_chunk_and_question_skips_answered_chunks():
    client = MagicMock()
    client.get_qa_content.return_value = [{"chunk_id": "base", "content": "正文"}]
    client.get_document_es_chunk.return_value = {
        "documents": [
            {"page_content": "已答", "metadata": {"chunk_id": "q1", "base_chunk_id": "base", "qa_answer": "yes"}},
            {"page_content": "未答", "metadata": {"chunk_id": "q2", "base_chunk_id": "base"}},
        ]
    }
    qa = MagicMock(id=9, document_id=3)
    rows = tasks.get_chunk_and_question(client, "idx", qa)
    assert rows == [{"question": "未答", "id": "q2", "content": "正文"}]


def test_rebuild_and_create_graph_mark_failed_or_completed(monkeypatch):
    monkeypatch.setattr(tasks, "_run_in_native_thread", lambda fn, *a, **k: fn(*a, **k))
    kb = KnowledgeBase.objects.create(name="g-kb", team=[1])
    llm = LLMModel.objects.create(name="g-llm", model="gpt")
    graph = KnowledgeGraph.objects.create(knowledge_base=kb, llm_model=llm, status="completed")
    with patch("apps.opspilot.tasks.GraphUtils.rebuild_graph_community", return_value={"result": False}):
        tasks.rebuild_graph_community_by_instance(graph.id)
    graph.refresh_from_db()
    assert graph.status == "failed"

    with patch("apps.opspilot.tasks.GraphUtils.rebuild_graph_community", return_value={"result": True}):
        tasks.rebuild_graph_community_by_instance(graph.id)
    graph.refresh_from_db()
    assert graph.status == "completed"

    with patch("apps.opspilot.tasks.GraphUtils.create_graph", return_value={"result": False, "message": "x"}):
        tasks.create_graph(graph.id)
    graph.refresh_from_db()
    assert graph.status == "failed"

    with patch("apps.opspilot.tasks.GraphUtils.create_graph", return_value={"result": True}):
        tasks.create_graph(graph.id)
    graph.refresh_from_db()
    assert graph.status == "completed"

    with patch("apps.opspilot.tasks.GraphUtils.update_graph", return_value={"result": False, "message": "u"}):
        tasks.update_graph(graph.id, [])
    graph.refresh_from_db()
    assert graph.status == "failed"
