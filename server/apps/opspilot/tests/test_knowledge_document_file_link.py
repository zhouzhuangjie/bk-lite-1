"""KnowledgeDocument.get_file_link：非文件与缺失文件契约。"""
import json

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.models import User
from apps.opspilot.enum import DocumentStatus
from apps.opspilot.models import KnowledgeBase, KnowledgeDocument
from apps.opspilot.viewsets.knowledge_document_view import KnowledgeDocumentViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()


def _su():
    user = User.objects.create_user(
        username=f"kd_file_{User.objects.count()}",
        password="x",
        domain="domain.com",
        locale="zh-Hans",
        group_list=[{"id": 1, "name": "T1"}],
    )
    user.is_superuser = True
    user.save()
    return user


def _dispatch(doc, user):
    req = factory.get(f"/knowledge_document/{doc.id}/get_file_link/")
    force_authenticate(req, user=user)
    req.COOKIES["current_team"] = "1"
    return KnowledgeDocumentViewSet.as_view({"get": "get_file_link"})(req, pk=doc.id)


def test_get_file_link_rejects_non_file_and_missing_file_object():
    user = _su()
    kb = KnowledgeBase.objects.create(name="kb-file", team=[1])
    manual = KnowledgeDocument.objects.create(
        knowledge_base=kb,
        name="manual.md",
        knowledge_source_type="manual",
        train_status=DocumentStatus.PENDING,
    )
    resp = _dispatch(manual, user)
    body = json.loads(resp.content)
    assert body["result"] is False
    assert body["message"] == "不是文件"

    file_doc = KnowledgeDocument.objects.create(
        knowledge_base=kb,
        name="a.pdf",
        knowledge_source_type="file",
        train_status=DocumentStatus.PENDING,
    )
    missing = _dispatch(file_doc, user)
    missing_body = json.loads(missing.content)
    assert missing_body["result"] is False
    assert missing_body["message"] == "未找到文件"
