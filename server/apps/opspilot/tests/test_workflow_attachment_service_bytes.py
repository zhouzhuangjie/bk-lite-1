"""workflow_attachment_service：类型归一化、字节生成、附件 ID 冲突与覆盖替换。"""
from datetime import timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.core import signing
from django.core.files.storage import FileSystemStorage
from django.utils import timezone

from apps.opspilot.models import FileKnowledge, WorkflowAttachmentAsset
from apps.opspilot.models.knowledge_mgmt import FileKnowledge as FileKnowledgeModel
from apps.opspilot.services import workflow_attachment_service as svc

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _local_file_storage(tmp_path):
    field = FileKnowledgeModel._meta.get_field("file")
    previous = field.storage
    field.storage = FileSystemStorage(location=str(tmp_path))
    yield
    field.storage = previous


def test_normalize_attachment_file_type_from_filename_and_rejects_unknown():
    kind, filename, mime = svc.normalize_attachment_file_type("", "日报.md")
    assert kind == "md"
    assert filename == "日报.md"
    assert mime == "text/markdown"

    kind, filename, mime = svc.normalize_attachment_file_type("word", "brief")
    assert kind == "word"
    assert filename == "brief.docx"
    assert mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    with pytest.raises(ValueError, match="不支持的附件类型: bin"):
        svc.normalize_attachment_file_type("bin", "a.bin")


def test_build_attachment_bytes_md_docx_pdf_and_escape():
    md = svc.build_attachment_bytes("# hello", "md")
    assert md == b"# hello"

    docx = svc.build_attachment_bytes("line-one\nline-two", "docx", title="报告")
    assert docx[:2] == b"PK"

    pdf = svc.build_attachment_bytes("alpha & <beta>", "pdf", title="标题")
    assert pdf.startswith(b"%PDF")
    assert svc._escape_pdf_text("a & b <c>") == "a &amp; b &lt;c&gt;"


def test_resolve_pdf_font_uses_first_registered_then_falls_back_to_helvetica():
    with patch.object(svc, "TTFont", return_value=MagicMock()), patch.object(svc.pdfmetrics, "registerFont", return_value=None):
        assert svc._resolve_pdf_font() == "微软雅黑"

    with patch.object(svc, "TTFont", side_effect=OSError("missing")):
        assert svc._resolve_pdf_font() == "Helvetica"


def test_build_workflow_attachment_id_requested_uuid_and_collision():
    assert svc.build_workflow_attachment_id(execution_id="e1", requested_attachment_id=" custom-id ") == "custom-id"
    generated = svc.build_workflow_attachment_id(execution_id="", source_node_id="")
    assert len(generated) == 12

    first = svc.create_workflow_attachment_asset(
        execution_id="exec-id-collision",
        attachment_id="agent_node",
        filename="a.md",
        content_bytes=b"a",
        mime_type="text/markdown",
        source_node_id="agent_node",
    )
    assert svc.build_workflow_attachment_id(execution_id="exec-id-collision", source_node_id="agent_node") == "agent_node__1"
    second = svc.create_workflow_attachment_asset(
        execution_id="exec-id-collision",
        attachment_id="agent_node__1",
        filename="b.md",
        content_bytes=b"b",
        mime_type="text/markdown",
        source_node_id="agent_node",
    )
    assert svc.build_workflow_attachment_id(execution_id="exec-id-collision", source_node_id="agent_node") == "agent_node__2"
    assert first.attachment_id == "agent_node"
    assert second.attachment_id == "agent_node__1"


def test_create_workflow_attachment_asset_replaces_previous_file_and_requires_ids():
    with pytest.raises(ValueError, match="execution_id 不能为空"):
        svc.create_workflow_attachment_asset(
            execution_id="",
            attachment_id="a1",
            filename="a.md",
            content_bytes=b"a",
            mime_type="text/markdown",
        )
    with pytest.raises(ValueError, match="attachment_id 不能为空"):
        svc.create_workflow_attachment_asset(
            execution_id="e1",
            attachment_id="",
            filename="a.md",
            content_bytes=b"a",
            mime_type="text/markdown",
        )

    first = svc.create_workflow_attachment_asset(
        execution_id="exec-replace",
        attachment_id="att-1",
        filename="old.md",
        content_bytes=b"old",
        mime_type="text/markdown",
        created_by="alice",
    )
    old_fk_id = first.file_knowledge_id
    second = svc.create_workflow_attachment_asset(
        execution_id="exec-replace",
        attachment_id="att-1",
        filename="new.md",
        content_bytes=b"new",
        mime_type="text/markdown",
        created_by="bob",
    )
    assert second.id == first.id
    assert second.filename == "new.md"
    assert second.created_by == "bob"
    assert second.file_knowledge_id != old_fk_id
    assert not FileKnowledge.objects.filter(id=old_fk_id).exists()


def test_resolve_signed_attachment_token_rejects_mismatch_and_malformed():
    asset = svc.create_workflow_attachment_asset(
        execution_id="exec-token",
        attachment_id=uuid4().hex[:8],
        filename="t.md",
        content_bytes=b"t",
        mime_type="text/markdown",
    )
    token = signing.dumps({"aid": asset.id, "eid": asset.execution_id}, salt=svc.WORKFLOW_ATTACHMENT_DOWNLOAD_SALT)
    assert svc.resolve_signed_attachment_token(token).id == asset.id

    mismatch = signing.dumps({"aid": asset.id, "eid": "other-exec"}, salt=svc.WORKFLOW_ATTACHMENT_DOWNLOAD_SALT)
    assert svc.resolve_signed_attachment_token(mismatch) is None

    with pytest.raises(signing.BadSignature, match="Malformed download token payload"):
        with patch.object(svc.signing, "loads", return_value="not-a-dict"):
            svc.resolve_signed_attachment_token("unused")


def test_cleanup_expired_workflow_attachments_counts_deleted_assets():
    asset = svc.create_workflow_attachment_asset(
        execution_id="exec-expire",
        attachment_id="expire-1",
        filename="o.md",
        content_bytes=b"o",
        mime_type="text/markdown",
    )
    fk_id = asset.file_knowledge_id
    WorkflowAttachmentAsset.objects.filter(id=asset.id).update(created_at=timezone.now() - timedelta(days=9))
    deleted = svc.cleanup_expired_workflow_attachments(retention_days=3)
    assert deleted == 1
    assert not WorkflowAttachmentAsset.objects.filter(id=asset.id).exists()
    assert not FileKnowledge.objects.filter(id=fk_id).exists()
