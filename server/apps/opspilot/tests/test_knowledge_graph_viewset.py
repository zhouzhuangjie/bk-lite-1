"""KnowledgeGraphViewSet：禁用 list、详情/删除/重建的权限与状态守卫。"""
import json
import uuid
from unittest.mock import patch

import pytest
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.opspilot.models import KnowledgeBase, KnowledgeGraph, LLMModel
from apps.opspilot.viewsets.knowledge_graph_view import KnowledgeGraphViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()
MOD = "apps.opspilot.viewsets.knowledge_graph_view"


def _su(name="kg-admin"):
    return UserFactory(username=f"{name}-{uuid.uuid4().hex[:8]}", domain="domain.com", roles=[], is_superuser=True, group_list=[{"id": 1, "name": "T1"}])


def _body(resp):
    return json.loads(resp.content.decode("utf-8"))


def _dispatch(action, method, *, data=None, query="", user=None, pk=None):
    if method in ("post", "patch"):
        request = getattr(factory, method)(f"/{query}", data=data or {}, format="json")
    else:
        request = factory.get(f"/{query}")
    force_authenticate(request, user=user or _su())
    request.COOKIES["current_team"] = "1"
    view = KnowledgeGraphViewSet.as_view({method: action})
    if pk is not None:
        return view(request, pk=pk)
    return view(request)


def test_list_disabled_returns_405():
    resp = _dispatch("list", "get")
    assert resp.status_code == 405
    assert _body(resp)["result"] is False


def test_validate_knowledge_base_permission_checks_team():
    view = KnowledgeGraphViewSet()
    view.loader = None
    kb = KnowledgeBase.objects.create(name="kg-kb", team=[9])
    guest = UserFactory(
        username=f"kg-guest-{uuid.uuid4().hex[:8]}",
        domain="domain.com",
        roles=[],
        is_superuser=False,
        group_list=[{"id": 2, "name": "other"}],
    )
    guest.is_superuser = False
    req = factory.get("/")
    req.user = guest
    req.COOKIES["current_team"] = "99"
    with pytest.raises(PermissionDenied):
        view._validate_knowledge_base_permission(req, kb)

    req.COOKIES["current_team"] = "2"
    with pytest.raises(PermissionDenied):
        view._validate_knowledge_base_permission(req, kb)

    su = _su("kg-su")
    req.user = su
    view._validate_knowledge_base_permission(req, kb)


def test_get_details_pending_completed_and_graph_error():
    kb = KnowledgeBase.objects.create(name="kg-det", team=[1])
    missing = _dispatch("get_details", "get", query="?knowledge_base_id=999999")
    assert missing.status_code == 404

    empty = _dispatch("get_details", "get", query=f"?knowledge_base_id={kb.id}")
    assert _body(empty)["data"]["is_exists"] is False

    llm = LLMModel.objects.create(name="kg-llm", model="gpt")
    graph = KnowledgeGraph.objects.create(knowledge_base=kb, llm_model=llm, status="pending")
    pending = _dispatch("get_details", "get", query=f"?knowledge_base_id={kb.id}")
    body = _body(pending)
    assert body["data"]["status"] == "pending"
    assert body["data"]["graph_id"] == graph.id

    graph.status = "completed"
    graph.save()
    with patch(f"{MOD}.GraphUtils.get_graph", return_value={"result": False, "message": "down"}):
        failed = _dispatch("get_details", "get", query=f"?knowledge_base_id={kb.id}")
    assert _body(failed)["result"] is False

    with patch(f"{MOD}.GraphUtils.get_graph", return_value={"result": True, "data": {"nodes": [1]}}):
        ok = _dispatch("get_details", "get", query=f"?knowledge_base_id={kb.id}")
    assert _body(ok)["data"]["graph"] == {"nodes": [1]}


def test_delete_graph_guards_training_and_deletes_completed():
    kb = KnowledgeBase.objects.create(name="kg-del", team=[1])
    missing_kb = _dispatch("delete_graph", "post", data={"knowledge_base_id": 999999})
    assert missing_kb.status_code == 404

    missing_g = _dispatch("delete_graph", "post", data={"knowledge_base_id": kb.id})
    assert missing_g.status_code == 404

    llm = LLMModel.objects.create(name="kg-del-llm", model="gpt")
    graph = KnowledgeGraph.objects.create(knowledge_base=kb, llm_model=llm, status="training")
    training = _dispatch("delete_graph", "post", data={"knowledge_base_id": kb.id})
    assert _body(training)["result"] is False

    graph.status = "completed"
    graph.save()
    with patch(f"{MOD}.GraphUtils.delete_graph", side_effect=RuntimeError("boom")):
        err = _dispatch("delete_graph", "post", data={"knowledge_base_id": kb.id})
    assert err.status_code == 500

    with patch(f"{MOD}.GraphUtils.delete_graph"), patch(f"{MOD}.log_operation"):
        ok = _dispatch("delete_graph", "post", data={"knowledge_base_id": kb.id})
    assert _body(ok)["result"] is True
    assert not KnowledgeGraph.objects.filter(id=graph.id).exists()


def test_rebuild_graph_community_only_when_completed():
    kb = KnowledgeBase.objects.create(name="kg-reb", team=[1])
    missing = _dispatch("rebuild_graph_community", "post", data={"knowledge_base_id": 999999})
    assert missing.status_code == 404

    none = _dispatch("rebuild_graph_community", "post", data={"knowledge_base_id": kb.id})
    assert _body(none)["result"] is False

    llm = LLMModel.objects.create(name="kg-reb-llm", model="gpt")
    graph = KnowledgeGraph.objects.create(knowledge_base=kb, llm_model=llm, status="pending")
    not_done = _dispatch("rebuild_graph_community", "post", data={"knowledge_base_id": kb.id})
    assert _body(not_done)["result"] is False

    graph.status = "completed"
    graph.save()
    with patch(f"{MOD}.rebuild_graph_community_by_instance") as task:
        ok = _dispatch("rebuild_graph_community", "post", data={"knowledge_base_id": kb.id})
    assert _body(ok)["result"] is True
    task.delay.assert_called_once_with(graph.id)

    with patch(f"{MOD}.rebuild_graph_community_by_instance") as task:
        task.delay.side_effect = RuntimeError("queue down")
        failed = _dispatch("rebuild_graph_community", "post", data={"knowledge_base_id": kb.id})
    assert _body(failed)["result"] is False
