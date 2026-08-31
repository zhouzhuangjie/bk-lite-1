"""KnowledgeDocumentViewSet 剩余：图谱/QA 任务、图检索、批量删除 ES 失败、网页同步、OCR 解析。"""
import json

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.models import User
from apps.opspilot.enum import DocumentStatus
from apps.opspilot.models import KnowledgeBase, KnowledgeDocument, KnowledgeTask, OCRProvider, WebPageKnowledge
from apps.opspilot.viewsets.knowledge_document_view import KnowledgeDocumentViewSet

pytestmark = pytest.mark.django_db
KD_MOD = "apps.opspilot.viewsets.knowledge_document_view"


def _body(resp):
    return json.loads(resp.content.decode("utf-8"))


def _su():
    user = User.objects.create_user(
        username=f"kd_rem_{User.objects.count()}",
        password="x",
        domain="domain.com",
        locale="zh-Hans",
        group_list=[{"id": 1, "name": "T1"}],
    )
    user.is_superuser = True
    user.save()
    return user


def _dispatch(action_name, method, *, data=None, query="", user=None, pk=None):
    factory = APIRequestFactory()
    path = f"/{query}"
    request = factory.post(path, data=data or {}, format="json") if method == "post" else factory.get(path)
    force_authenticate(request, user=user or _su())
    request.COOKIES["current_team"] = "1"
    view = KnowledgeDocumentViewSet.as_view({method: action_name})
    if pk is not None:
        return view(request, pk=pk)
    return view(request)


def test_get_my_tasks_graph_and_qa_filters():
    kb = KnowledgeBase.objects.create(name="图谱库", team=[1])
    user = _su()
    KnowledgeTask.objects.create(
        task_name="图谱库-图谱",
        knowledge_base_id=kb.id,
        created_by=user.username,
        domain=user.domain,
        completed_count=1,
        total_count=2,
    )
    KnowledgeTask.objects.create(
        task_name="qa-task",
        knowledge_base_id=kb.id,
        created_by=user.username,
        domain=user.domain,
        is_qa_task=True,
        completed_count=4,
        total_count=4,
    )
    KnowledgeTask.objects.create(
        task_name="normal",
        knowledge_base_id=kb.id,
        created_by=user.username,
        domain=user.domain,
        is_qa_task=False,
        completed_count=0,
        total_count=1,
    )
    graph = _dispatch("get_my_tasks", "get", query=f"?knowledge_base_id={kb.id}&is_graph=1", user=user)
    body = _body(graph)
    assert body["result"] is True
    assert [row["task_name"] for row in body["data"]] == ["图谱库-图谱"]
    assert body["data"][0]["train_progress"] == "1/2"

    qa = _dispatch("get_my_tasks", "get", query=f"?knowledge_base_id={kb.id}&is_qa_task=1", user=user)
    names = [row["task_name"] for row in _body(qa)["data"]]
    assert names == ["qa-task"]


def test_testing_graph_rag_appends_graph_list(mocker):
    kb = KnowledgeBase.objects.create(name="gkb", team=[1])
    mocker.patch(f"{KD_MOD}.KnowledgeSearchService").return_value.search.return_value = []
    mocker.patch(f"{KD_MOD}.KnowledgeGraph.objects.filter").return_value.first.return_value = object()
    mocker.patch(f"{KD_MOD}.GraphUtils.search_graph", return_value={"result": True, "data": [{"id": "n1"}]})
    resp = _dispatch(
        "testing",
        "post",
        data={
            "knowledge_base_id": kb.id,
            "query": "q",
            "enable_naive_rag": False,
            "enable_qa_rag": False,
            "enable_graph_rag": True,
            "graph_size": 5,
        },
    )
    body = _body(resp)
    assert body["result"] is True
    assert body["data"]["graph_data"] == [{"id": "n1"}]


def test_get_chunk_detail_graph_missing_returns_not_found():
    resp = _dispatch("get_chunk_detail", "get", query="?knowledge_id=graph-999&chunk_id=c1&type=Graph")
    assert _body(resp) == {"result": True, "message": "未找到知识图谱"}


def test_get_graph_detail_returns_search_payload(mocker):
    vs = KnowledgeDocumentViewSet()
    mocker.patch(f"{KD_MOD}.KnowledgeGraph.objects.filter").return_value.first.return_value = object()
    mocker.patch(f"{KD_MOD}.GraphUtils.search_graph", return_value={"result": True, "data": [{"n": 1}]})
    resp = vs.get_graph_detail(3, "chunk-9")
    assert json.loads(resp.content) == {"result": True, "data": [{"n": 1}]}


def test_batch_delete_returns_false_when_es_delete_fails(mocker):
    kb = KnowledgeBase.objects.create(name="del-kb", team=[1])
    doc = KnowledgeDocument.objects.create(
        knowledge_base=kb, name="d1", knowledge_source_type="manual", train_status=DocumentStatus.PENDING
    )
    mocker.patch(f"{KD_MOD}.KnowledgeSearchService.delete_es_content", side_effect=RuntimeError("es down"))
    mocker.patch(f"{KD_MOD}.log_operation")
    resp = _dispatch("batch_delete", "post", data={"doc_ids": [doc.id], "knowledge_base_id": kb.id})
    assert _body(resp) == {"result": False, "message": "删除失败"}


def test_update_document_base_info_toggles_web_page_sync(mocker):
    kb = KnowledgeBase.objects.create(name="web-kb", team=[1])
    doc = KnowledgeDocument.objects.create(
        knowledge_base=kb, name="page", knowledge_source_type="web_page", train_status=DocumentStatus.PENDING
    )
    page = WebPageKnowledge.objects.create(knowledge_document=doc, url="https://example.com/", sync_enabled=False)
    create = mocker.patch.object(WebPageKnowledge, "create_sync_periodic_task")
    delete = mocker.patch.object(WebPageKnowledge, "delete_sync_periodic_task")
    resp = _dispatch(
        "update_document_base_info",
        "post",
        data={"sync_enabled": True, "url": "https://example.com/"},
        pk=doc.id,
    )
    assert _body(resp)["result"] is True
    create.assert_called_once()
    delete.assert_not_called()
    page.refresh_from_db()
    assert page.sync_enabled is True

    resp = _dispatch("update_document_base_info", "post", data={"sync_enabled": False}, pk=doc.id)
    assert _body(resp)["result"] is True
    delete.assert_called_once()


def test_update_parse_settings_sets_ocr_model():
    kb = KnowledgeBase.objects.create(name="ocr-kb", team=[1])
    doc = KnowledgeDocument.objects.create(
        knowledge_base=kb, name="ocr-doc", knowledge_source_type="file", train_status=DocumentStatus.PENDING
    )
    ocr = OCRProvider.objects.create(name="ocr-for-parse", model="olm")
    resp = _dispatch(
        "update_parse_settings",
        "post",
        data={"knowledge_document_list": [{"id": doc.id, "enable_ocr_parse": True, "ocr_model": ocr.id, "mode": "full"}]},
    )
    assert _body(resp)["result"] is True
    doc.refresh_from_db()
    assert doc.enable_ocr_parse is True
    assert doc.ocr_model_id == ocr.id
