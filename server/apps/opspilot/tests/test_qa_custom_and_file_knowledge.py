"""create_qa_pairs_by_custom 任务状态，以及文件知识导入成功/跳过/失败。"""
import json
import uuid
from unittest.mock import MagicMock

import pytest
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.opspilot import tasks as ops_tasks
from apps.opspilot.models import EmbedProvider, KnowledgeBase, KnowledgeDocument, KnowledgeTask, ModelVendor, QAPairs
from apps.opspilot.models.knowledge_mgmt import FileKnowledge as FileKnowledgeModel
from apps.opspilot.viewsets.file_knowledge_view import FileKnowledgeViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()


@pytest.fixture(autouse=True)
def _local_file_storage(tmp_path):
    field = FileKnowledgeModel._meta.get_field("file")
    previous = field.storage
    field.storage = FileSystemStorage(location=str(tmp_path))
    yield
    field.storage = previous


def _kb():
    vendor = ModelVendor.objects.create(
        name=f"v-{uuid.uuid4().hex[:6]}", api_base="http://embed.local", api_key="k", team=[1]
    )
    embed = EmbedProvider.objects.create(name="emb-fk", vendor=vendor, model="bge", team=[1])
    return KnowledgeBase.objects.create(name=f"kb-{uuid.uuid4().hex[:6]}", team=[1], embed_model=embed)


def test_create_qa_pairs_by_custom_completed_and_failed(monkeypatch):
    kb = _kb()
    qa = QAPairs.objects.create(
        name="qa-custom",
        knowledge_base=kb,
        document_id=0,
        create_type="custom",
        status="pending",
        generate_count=0,
    )
    create_mock = MagicMock(return_value=5)
    monkeypatch.setattr(ops_tasks.ChunkHelper, "create_qa_pairs", create_mock)

    ops_tasks.create_qa_pairs_by_custom(qa.id, [{"q": "什么是 CPU", "a": "处理器"}])
    qa.refresh_from_db()
    assert qa.status == "completed"
    assert qa.generate_count == 5
    assert KnowledgeTask.objects.filter(knowledge_base_id=kb.id).count() == 0
    create_mock.assert_called_once()
    args = create_mock.call_args.args
    assert args[0] == [{"q": "什么是 CPU", "a": "处理器"}]
    assert args[4] == qa.id

    create_mock.side_effect = RuntimeError("es down")
    ops_tasks.create_qa_pairs_by_custom(qa.id, [{"q": "x", "a": "y"}])
    qa.refresh_from_db()
    assert qa.status == "failed"
    assert KnowledgeTask.objects.filter(knowledge_base_id=kb.id).count() == 0


def test_import_file_knowledge_creates_docs_skips_empty_and_catches_error(monkeypatch):
    kb = _kb()
    view = FileKnowledgeViewSet()
    view.loader = None
    ok_file = SimpleUploadedFile("runbook.md", "# 手册".encode("utf-8"), content_type="text/markdown")
    empty = MagicMock()
    empty.name = ""
    empty.read.side_effect = AssertionError("empty title must be skipped")
    result = view.import_file_knowledge(
        [empty, ok_file],
        {"knowledge_base_id": kb.id},
        "alice",
        "domain.com",
    )
    assert result["result"] is True
    assert len(result["data"]) == 1
    doc = KnowledgeDocument.objects.get(id=result["data"][0])
    assert doc.name == "runbook.md"
    assert doc.knowledge_source_type == "file"
    assert doc.created_by == "alice"
    assert FileKnowledgeModel.objects.filter(knowledge_document_id=doc.id).exists()

    view.loader = MagicMock()
    view.loader.get.return_value = "Failed to import file."

    def _boom(*_a, **_k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(KnowledgeDocument, "create_new_document", _boom)
    failed = view.import_file_knowledge(
        [SimpleUploadedFile("x.md", b"x", content_type="text/markdown")],
        {"knowledge_base_id": kb.id},
        "alice",
        "domain.com",
    )
    assert failed["result"] is False
    assert failed["message"] == "Failed to import file."


def test_create_file_knowledge_requires_base_and_imports(monkeypatch):
    kb = _kb()
    user = UserFactory(username=f"fk-{uuid.uuid4().hex[:8]}", domain="domain.com", is_superuser=True)
    user.locale = "en"
    missing = factory.post("/knowledge_mgmt/file_knowledge/create_file_knowledge/", {}, format="multipart")
    force_authenticate(missing, user=user)
    missing.COOKIES["current_team"] = "1"
    resp = FileKnowledgeViewSet.as_view({"post": "create_file_knowledge"})(missing)
    missing_body = json.loads(resp.content)
    assert missing_body["result"] is False
    assert missing_body["message"]

    upload = SimpleUploadedFile("guide.md", b"# g", content_type="text/markdown")
    ok = factory.post(
        "/knowledge_mgmt/file_knowledge/create_file_knowledge/",
        {"knowledge_base_id": kb.id, "files": upload},
        format="multipart",
    )
    force_authenticate(ok, user=user)
    ok.COOKIES["current_team"] = "1"
    monkeypatch.setattr("apps.opspilot.viewsets.file_knowledge_view.log_operation", lambda *a, **k: None)
    created = FileKnowledgeViewSet.as_view({"post": "create_file_knowledge"})(ok)
    created_body = json.loads(created.content)
    assert created_body["result"] is True
    assert KnowledgeDocument.objects.filter(knowledge_base=kb, name="guide.md").exists()
