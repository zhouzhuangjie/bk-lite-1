"""create_qa_pairs_by_chunk：状态切 generating → completed，并按 chunk 调 ChunkHelper。"""
import uuid
from unittest.mock import MagicMock

import pytest

from apps.opspilot.models import EmbedProvider, KnowledgeBase, KnowledgeTask, LLMModel, ModelVendor, QAPairs
from apps.opspilot import tasks as ops_tasks

pytestmark = pytest.mark.django_db


def test_create_qa_pairs_by_chunk_marks_completed_and_counts(monkeypatch):
    vendor = ModelVendor.objects.create(
        name=f"v-{uuid.uuid4().hex[:6]}", api_base="http://llm.local", api_key="k", team=[1]
    )
    embed = EmbedProvider.objects.create(name="emb-qa", vendor=vendor, model="bge", team=[1])
    kb = KnowledgeBase.objects.create(name="kb-qa", team=[1], embed_model=embed)
    llm = LLMModel.objects.create(name="llm-qa", vendor=vendor, model="gpt", team=[1])
    qa = QAPairs.objects.create(
        name="qa-chunk",
        knowledge_base=kb,
        llm_model=llm,
        answer_llm_model=llm,
        document_id=88,
        generate_count=1,
        status="pending",
    )
    helper = MagicMock()
    helper.create_qa_pairs_by_content.return_value = 3
    monkeypatch.setattr(ops_tasks, "ChunkHelper", lambda: helper)

    ops_tasks.create_qa_pairs_by_chunk(
        qa.id,
        {
            "chunk_list": [{"id": "c1", "content": "正文"}],
            "llm_model_id": llm.id,
            "answer_llm_model_id": llm.id,
            "qa_count": 2,
            "question_prompt": "q?",
            "answer_prompt": "a?",
            "only_question": False,
        },
    )
    qa.refresh_from_db()
    assert qa.status == "completed"
    assert qa.generate_count == 4
    args, kwargs = helper.create_qa_pairs_by_content.call_args
    assert args[0] == [{"chunk_id": "c1", "content": "正文", "knowledge_id": 88}]
    assert args[4] == qa
    assert args[5] == 2
    assert KnowledgeTask.objects.filter(knowledge_base_id=kb.id).count() == 0
