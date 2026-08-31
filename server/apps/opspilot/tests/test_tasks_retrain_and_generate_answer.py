"""opspilot.tasks：retrain_all 置 CHUNKING；generate_answer 回写未答 QA。"""
from unittest.mock import MagicMock, patch

import pytest

from apps.opspilot import tasks
from apps.opspilot.enum import DocumentStatus
from apps.opspilot.models import KnowledgeDocument

pytestmark = pytest.mark.unit


def test_retrain_all_marks_chunking_then_embeds():
    qs = MagicMock()
    with patch.object(KnowledgeDocument.objects, "filter", return_value=qs) as filt, patch(
        "apps.opspilot.tasks.general_embed_by_document_list"
    ) as embed:
        tasks.retrain_all(12, "alice", "domain.com", True)
    filt.assert_called_once_with(knowledge_base_id=12)
    qs.update.assert_called_once_with(train_status=DocumentStatus.CHUNKING)
    embed.assert_called_once_with(qs, username="alice", domain="domain.com", delete_qa_pairs=True)


def test_generate_answer_forwards_unanswered_chunks():
    kb = MagicMock()
    kb.knowledge_index_name.return_value = "knowledge_base_3"
    qa = MagicMock(id=5, knowledge_base=kb)
    helper = MagicMock()
    rows = [{"question": "未答", "id": "q2", "content": "正文"}]
    with patch("apps.opspilot.tasks.QAPairs.objects.get", return_value=qa) as get_qa, patch(
        "apps.opspilot.tasks.ChunkHelper", return_value=helper
    ), patch("apps.opspilot.tasks.get_chunk_and_question", return_value=rows) as get_rows:
        tasks.generate_answer(5)
    get_qa.assert_called_once_with(id=5)
    get_rows.assert_called_once_with(helper, "knowledge_base_3", qa)
    helper.update_qa_pairs_answer.assert_called_once_with(rows, qa)
