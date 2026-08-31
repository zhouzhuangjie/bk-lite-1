"""网页知识同步：缺记录短路、清理失败标记 ERROR、清理成功后重训。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.opspilot import tasks
from apps.opspilot.enum import DocumentStatus

pytestmark = pytest.mark.django_db


def test_sync_web_page_knowledge_missing_returns():
    with patch.object(tasks.WebPageKnowledge.objects, "filter") as flt:
        flt.return_value.first.return_value = None
        assert tasks.sync_web_page_knowledge(999999) is None


def test_sync_web_page_knowledge_cleanup_failure_marks_error():
    document = SimpleNamespace(train_status=DocumentStatus.CHUNKING, error_message="", created_by="u", domain="d")
    document.save = MagicMock()
    web_page = SimpleNamespace(id=8, knowledge_document=document)
    web_page.save = MagicMock()
    with (
        patch.object(tasks.WebPageKnowledge.objects, "filter") as flt,
        patch.object(tasks, "delete_and_update_old_data", return_value=False),
        patch.object(tasks, "general_embed_by_document_list") as embed,
        patch.object(tasks.timezone, "now", return_value="now"),
    ):
        flt.return_value.first.return_value = web_page
        tasks.sync_web_page_knowledge(8)
    assert document.train_status == DocumentStatus.ERROR
    assert "清理旧数据失败" in document.error_message
    document.save.assert_called()
    embed.assert_not_called()


def test_sync_web_page_knowledge_reembeds_after_cleanup():
    document = SimpleNamespace(train_status=None, error_message="", created_by="alice", domain="domain.com")
    document.save = MagicMock()
    web_page = SimpleNamespace(id=9, knowledge_document=document)
    web_page.save = MagicMock()
    with (
        patch.object(tasks.WebPageKnowledge.objects, "filter") as flt,
        patch.object(tasks, "delete_and_update_old_data", return_value=True),
        patch.object(tasks, "general_embed_by_document_list") as embed,
        patch.object(tasks.timezone, "now", return_value="now"),
    ):
        flt.return_value.first.return_value = web_page
        tasks.sync_web_page_knowledge(9)
    embed.assert_called_once_with([document], False, "alice", "domain.com")


def test_delete_and_update_old_data_es_failure_is_fatal():
    document = MagicMock()
    document.id = 3
    document.knowledge_index_name.return_value = "kb"
    web_page = SimpleNamespace(id=1, knowledge_document=document)
    with patch.object(tasks.KnowledgeSearchService, "delete_es_content", side_effect=RuntimeError("es down")):
        assert tasks.delete_and_update_old_data(web_page) is False


def test_delete_and_update_old_data_qa_refresh_failure_still_ok():
    document = MagicMock()
    document.id = 3
    document.knowledge_index_name.return_value = "kb"
    web_page = SimpleNamespace(id=2, knowledge_document=document)
    with (
        patch.object(tasks.KnowledgeSearchService, "delete_es_content"),
        patch.object(tasks.QAPairs.objects, "filter", side_effect=RuntimeError("qa down")),
    ):
        assert tasks.delete_and_update_old_data(web_page) is True
