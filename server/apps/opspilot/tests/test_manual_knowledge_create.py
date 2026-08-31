"""ManualKnowledgeViewSet.create_manual_knowledge：缺 KB 与创建成功。"""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.opspilot.viewsets.manual_knowledge_view import ManualKnowledgeViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()


def _actor():
    return UserFactory(is_superuser=True, domain="domain.com", group_list=[{"id": 1, "name": "T1"}])


def test_create_manual_knowledge_requires_knowledge_base_id():
    actor = _actor()
    actor.locale = "zh-Hans"
    request = factory.post("/", {}, format="json")
    force_authenticate(request, user=actor)
    request.COOKIES["current_team"] = "1"
    resp = ManualKnowledgeViewSet.as_view({"post": "create_manual_knowledge"})(request)
    assert json.loads(resp.content) == {"result": False, "message": "缺少 knowledge_base_id"}


def test_create_manual_knowledge_creates_document_and_logs():
    actor = _actor()
    request = factory.post("/", {"knowledge_base_id": 3, "name": "note-1", "content": "hello"}, format="json")
    force_authenticate(request, user=actor)
    request.COOKIES["current_team"] = "1"
    doc = SimpleNamespace(id=88)
    knowledge = SimpleNamespace(knowledge_document_id=88)
    with (
        patch.object(ManualKnowledgeViewSet, "_validate_knowledge_base_permission", return_value=SimpleNamespace()) as perm,
        patch(
            "apps.opspilot.viewsets.manual_knowledge_view.KnowledgeDocument.create_new_document",
            return_value=doc,
        ) as create_doc,
        patch(
            "apps.opspilot.viewsets.manual_knowledge_view.ManualKnowledge.objects.create",
            return_value=knowledge,
        ) as create_manual,
        patch("apps.opspilot.viewsets.manual_knowledge_view.log_operation") as log,
    ):
        resp = ManualKnowledgeViewSet.as_view({"post": "create_manual_knowledge"})(request)
    body = json.loads(resp.content)
    assert body == {"result": True, "data": 88}
    perm.assert_called_once()
    kwargs = create_doc.call_args.args[0]
    assert kwargs["knowledge_base_id"] == 3
    assert kwargs["knowledge_source_type"] == "manual"
    create_manual.assert_called_once_with(knowledge_document_id=88, content="hello")
    log.assert_called_once()
