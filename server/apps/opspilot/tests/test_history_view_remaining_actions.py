"""HistoryViewSet：禁用 CRUD、标签增删、search_log 参数与分页回退。"""
import json
import uuid
from unittest.mock import patch

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.opspilot.enum import ChannelChoices
from apps.opspilot.models import Bot, BotConversationHistory, ConversationTag, KnowledgeBase, KnowledgeDocument, ManualKnowledge
from apps.opspilot.viewsets.history_view import HistoryViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()
MOD = "apps.opspilot.viewsets.history_view"


def _su(name="hist-admin"):
    user = UserFactory(
        username=f"{name}-{uuid.uuid4().hex[:8]}",
        domain="domain.com",
        roles=[],
        is_superuser=True,
        group_list=[{"id": 1, "name": "T1"}],
    )
    user.permission = {"opspilot": {"bot_conversation_log-View", "bot_conversation_log-Mark"}}
    return user


def _body(resp):
    return json.loads(resp.content.decode("utf-8"))


def test_builtin_list_create_retrieve_disabled():
    user = _su("hist-dis")
    req = factory.get("/")
    force_authenticate(req, user=user)
    assert HistoryViewSet.as_view({"get": "list"})(req).status_code == 405
    req2 = factory.post("/", {}, format="json")
    force_authenticate(req2, user=user)
    assert HistoryViewSet.as_view({"post": "create"})(req2).status_code == 405
    req3 = factory.get("/1/")
    force_authenticate(req3, user=user)
    assert HistoryViewSet.as_view({"get": "retrieve"})(req3, pk=1).status_code == 405


def test_set_log_params_splits_channel_or_defaults_all():
    req = factory.get("/?channel_type=web,ding_talk&page=2&page_size=5&bot_id=9&search=alice")
    bot_id, channel_type, end_time, page, page_size, search, start_time = HistoryViewSet.set_log_params(req)
    assert bot_id == "9"
    assert channel_type == ["web", "ding_talk"]
    assert page == 2
    assert page_size == 5
    assert search == "alice"
    empty = factory.get("/")
    _, channels, *_ = HistoryViewSet.set_log_params(empty)
    assert set(channels) == set(dict(ChannelChoices.choices).keys())


def test_get_or_create_tag_creates_and_replaces_old_document():
    kb = KnowledgeBase.objects.create(name="hist-kb", team=[1])
    created = HistoryViewSet.get_or_create_tag(
        {"tag_id": 0, "knowledge_base_id": kb.id, "answer_id": None, "question": "q1", "content": "c1"}
    )
    assert created.question == "q1"
    doc = KnowledgeDocument.objects.create(knowledge_base=kb, name="old", knowledge_source_type="manual")
    created.knowledge_document_id = doc.id
    created.save()
    reused = HistoryViewSet.get_or_create_tag(
        {"tag_id": created.id, "knowledge_base_id": kb.id, "question": "q2", "content": "c2"}
    )
    assert reused.id == created.id
    assert reused.question == "q2"
    assert not KnowledgeDocument.objects.filter(id=doc.id).exists()


def test_set_tag_and_remove_tag_persist_manual_knowledge():
    user = _su("hist-tag")
    kb = KnowledgeBase.objects.create(name="hist-kb2", team=[1])
    req = factory.post(
        "/",
        {"tag_id": 0, "knowledge_base_id": kb.id, "question": "如何重启", "content": "systemctl restart"},
        format="json",
    )
    force_authenticate(req, user=user)
    req.COOKIES["current_team"] = "1"
    with patch(f"{MOD}.invoke_document_to_es") as task:
        resp = HistoryViewSet.as_view({"post": "set_tag"})(req)
    body = _body(resp)
    assert body["result"] is True
    tag = ConversationTag.objects.get(id=body["data"]["tag_id"])
    assert tag.question == "如何重启"
    assert ManualKnowledge.objects.filter(knowledge_document_id=tag.knowledge_document_id).exists()
    task.delay.assert_called_once()

    detail_req = factory.get(f"/?tag_id={tag.id}")
    force_authenticate(detail_req, user=user)
    detail = HistoryViewSet.as_view({"get": "get_tag_detail"})(detail_req)
    assert _body(detail)["data"]["question"] == "如何重启"

    rm = factory.post("/", {"tag_id": tag.id}, format="json")
    force_authenticate(rm, user=user)
    rm.COOKIES["current_team"] = "1"
    removed = HistoryViewSet.as_view({"post": "remove_tag"})(rm)
    assert _body(removed)["result"] is True
    assert not ConversationTag.objects.filter(id=tag.id).exists()


def test_get_log_by_page_falls_back_invalid_page_and_formats_ids():
    from datetime import datetime, timezone as tz

    stamp = datetime(2026, 1, 2, 3, 4, 5, 6000, tzinfo=tz.utc)
    entries = [
        {
            "ids": [11, 12],
            "channel_user__user_id": "u1",
            "channel_user__name": "alice",
            "channel_user__channel_type": "web",
            "count": 2,
            "earliest_created_at": stamp,
            "last_updated_at": stamp,
            "title": "hello",
        }
    ]
    paginator, result = HistoryViewSet.get_log_by_page(entries, page=99, page_size=1)
    assert paginator.count == 1
    assert result == [
        {
            "sender_id": "u1",
            "username": "alice",
            "channel_type": "Web",
            "count": 2,
            "ids": [11, 12],
            "created_at": "2026-01-02T03:04:05.006000Z",
            "updated_at": "2026-01-02T03:04:05.006000Z",
            "title": "hello",
        }
    ]
