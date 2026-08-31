"""KnowledgeDocument.get_graph_detail：图谱不存在。"""
import json
from types import SimpleNamespace

import pytest

from apps.opspilot.viewsets.knowledge_document_view import KnowledgeDocumentViewSet

pytestmark = pytest.mark.django_db


def test_get_graph_detail_returns_not_found_when_graph_missing():
    vs = KnowledgeDocumentViewSet()
    vs.loader = SimpleNamespace(get=lambda key, default=None: "未找到知识图谱" if key == "error.knowledge_graph_not_found" else default)
    resp = vs.get_graph_detail(999999, "chunk-1")
    body = json.loads(resp.content)
    assert body == {"result": True, "message": "未找到知识图谱"}
