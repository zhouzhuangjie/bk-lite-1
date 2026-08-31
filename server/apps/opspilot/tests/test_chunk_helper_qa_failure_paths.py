"""ChunkHelper QA 失败路径：检索失败、生成异常、答案跳过、空列表短路。"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.opspilot.utils.chunk_helper import ChunkHelper

pytestmark = pytest.mark.unit


def test_get_qa_content_raises_when_chunk_lookup_fails(monkeypatch):
    monkeypatch.setattr(
        ChunkHelper,
        "get_document_es_chunk",
        classmethod(lambda cls, *a, **k: {"status": "fail"}),
    )
    with pytest.raises(Exception, match="Failed to get document chunk for document ID 7"):
        ChunkHelper.get_qa_content(7, "idx")


def test_generate_question_and_answer_return_empty_on_exception(monkeypatch):
    monkeypatch.setattr(
        "apps.opspilot.utils.chunk_helper.QAGeneration.generate_question",
        lambda request: (_ for _ in ()).throw(RuntimeError("q fail")),
    )
    monkeypatch.setattr(
        "apps.opspilot.utils.chunk_helper.QAGeneration.generate_answer",
        lambda request: (_ for _ in ()).throw(RuntimeError("a fail")),
    )
    assert ChunkHelper.generate_question({"content": "doc"}) == {"result": False, "data": []}
    assert ChunkHelper.generate_answer({"context": "doc", "content": "q"}) == {"result": False, "data": {}}


def test_generate_qa_returns_zero_when_questions_fail(monkeypatch):
    monkeypatch.setattr(ChunkHelper, "generate_question", classmethod(lambda cls, kwargs: {"result": False, "data": []}))
    count = ChunkHelper.generate_qa({}, {}, {"content": "c", "chunk_id": "c1"}, {}, "idx", SimpleNamespace(id=1), False, SimpleNamespace())
    assert count == 0


def test_generate_qa_skips_failed_answers(monkeypatch):
    created = []
    monkeypatch.setattr(
        ChunkHelper,
        "generate_question",
        classmethod(lambda cls, kwargs: {"result": True, "data": [{"question": "q1"}, {"question": "q2"}]}),
    )
    monkeypatch.setattr(
        ChunkHelper,
        "generate_answer",
        classmethod(lambda cls, kwargs: {"result": False, "data": {}} if kwargs["content"] == "q1" else {"result": True, "data": {"answer": "a2"}}),
    )
    monkeypatch.setattr(ChunkHelper, "create_one_qa_pairs", classmethod(lambda cls, *a, **k: created.append(a[3])))
    task = SimpleNamespace(completed_count=0, save=MagicMock())
    count = ChunkHelper.generate_qa({}, {}, {"content": "c", "chunk_id": "c1"}, {}, "idx", SimpleNamespace(id=9), False, task)
    assert created == ["q2"]
    assert count == 1
    assert task.completed_count == 1
    task.save.assert_called_once()


def test_create_qa_pairs_by_content_and_document_delegate(monkeypatch):
    monkeypatch.setattr(ChunkHelper, "generate_qa", classmethod(lambda cls, *a, **k: 2))
    task = SimpleNamespace(completed_count=0)
    llm = {"question": {"model": "q"}, "answer": {"model": "a"}}
    assert ChunkHelper.create_qa_pairs_by_content([{"content": "c"}], {}, "idx", llm, SimpleNamespace(id=1), 3, "qp", "ap", task, True) == 2
    qa_pairs = SimpleNamespace(id=1, qa_count=3, question_prompt="qp", answer_prompt="ap")
    assert ChunkHelper.create_document_qa_pairs([{"content": "c"}], {}, "idx", llm, qa_pairs, False, task) == 2


def test_update_qa_pairs_answer_noop_and_skips_failures(monkeypatch):
    assert ChunkHelper.update_qa_pairs_answer([], SimpleNamespace()) is None
    updated = []
    monkeypatch.setattr(
        ChunkHelper,
        "generate_answer",
        classmethod(
            lambda cls, kwargs: {"result": False, "data": {}}
            if kwargs["content"] == "q1"
            else {"result": True, "data": {"answer": ""}}
            if kwargs["content"] == "q2"
            else {"result": True, "data": {"answer": "ok"}}
        ),
    )
    monkeypatch.setattr(ChunkHelper, "update_qa_pairs", classmethod(lambda cls, cid, q, a: updated.append((cid, q, a))))
    qa_pairs = SimpleNamespace(
        answer_prompt="p",
        answer_llm_model=SimpleNamespace(openai_api_base="http://e", openai_api_key="k", model_name="m"),
    )
    ChunkHelper.update_qa_pairs_answer(
        [
            {"id": "1", "question": "q1", "content": "c"},
            {"id": "2", "question": "q2", "content": "c"},
            {"id": "3", "question": "q3", "content": "c"},
        ],
        qa_pairs,
    )
    assert updated == [("3", "q3", "ok")]
