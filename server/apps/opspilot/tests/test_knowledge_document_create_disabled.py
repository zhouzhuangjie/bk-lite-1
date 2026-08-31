"""KnowledgeDocumentViewSet：禁用 create 返回中文 405。"""
import json

import pytest
from rest_framework.test import APIRequestFactory

from apps.opspilot.viewsets.knowledge_document_view import KnowledgeDocumentViewSet

pytestmark = pytest.mark.unit
factory = APIRequestFactory()


def test_create_disabled_returns_chinese_not_enabled():
    vs = KnowledgeDocumentViewSet()
    vs.loader = None
    resp = vs.create(factory.post("/knowledge_document/"))
    assert resp.status_code == 405
    assert json.loads(resp.content) == {"result": False, "message": "接口未启用"}
