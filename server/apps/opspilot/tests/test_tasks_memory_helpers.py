"""opspilot.tasks：线程回退、组织名解析、网页摄取、记忆合并计划。

对照契约：SynchronousOnlyOperation 时允许 async unsafe 重试；组织名优先组名；
网页摄取把 URL 交给 RAG；空记忆内容跳过 ingest。
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import SynchronousOnlyOperation

from apps.opspilot import tasks
from apps.system_mgmt.models import Group

pytestmark = pytest.mark.unit


def test_run_in_native_thread_retries_when_sync_only(monkeypatch):
    calls = []

    def fn(allow=False):
        calls.append(allow)
        if len(calls) == 1:
            raise SynchronousOnlyOperation("need async unsafe")
        return "ok"

    # _run_in_native_thread wraps func; simulate inner _execute raising then succeeding
    real_fn = MagicMock(side_effect=[SynchronousOnlyOperation("blocked"), "done"])

    def fake_submit(execute, allow_async_unsafe):
        fut = MagicMock()
        if not allow_async_unsafe:
            fut.result.side_effect = SynchronousOnlyOperation("blocked")
        else:
            fut.result.return_value = "done"
        return fut

    with patch("apps.opspilot.tasks.concurrent.futures.ThreadPoolExecutor") as pool:
        pool.return_value.__enter__.return_value.submit.side_effect = fake_submit
        assert tasks._run_in_native_thread(lambda: None) == "done"


def test_resolve_org_display_name_prefers_group(db):
    group = Group.objects.create(name="运维一组", parent_id=0)
    assert tasks._resolve_org_display_name(group.id) == "运维一组"
    assert tasks._resolve_org_display_name(999999) == "组织-999999"


def test_handle_manual_and_webpage_ingest_delegate_to_rag():
    rag = MagicMock()
    rag.custom_content_ingest.return_value = {"status": "ok"}
    rag.website_ingest.return_value = {"status": "web"}
    document = SimpleNamespace(
        id=1,
        name="手册标题",
        manualknowledge_set=SimpleNamespace(all=lambda: [SimpleNamespace(content="正文")]),
        webpageknowledge_set=SimpleNamespace(all=lambda: []),
    )
    assert tasks._handle_manual_ingest(document, {"k": 1}, rag) == {"status": "ok"}
    rag.custom_content_ingest.assert_called_once()
    assert rag.custom_content_ingest.call_args.kwargs["content"] == "手册标题正文"

    page = SimpleNamespace(url="https://example.com/docs", max_depth=2)
    document.webpageknowledge_set = SimpleNamespace(all=lambda: [page])
    assert tasks._handle_webpage_ingest(document, {"k": 2}, rag) == {"status": "web"}
    rag.website_ingest.assert_called_once()
    assert rag.website_ingest.call_args.kwargs["url"] == "https://example.com/docs"
    assert rag.website_ingest.call_args.kwargs["max_depth"] == 2


def test_handle_webpage_and_manual_ingest_missing_record_raises():
    empty = SimpleNamespace(
        id=9,
        webpageknowledge_set=SimpleNamespace(all=lambda: []),
        manualknowledge_set=SimpleNamespace(all=lambda: []),
    )
    with pytest.raises(ValueError, match="找不到网页知识记录"):
        tasks._handle_webpage_ingest(empty, {}, MagicMock())
    with pytest.raises(ValueError, match="找不到手动知识记录"):
        tasks._handle_manual_ingest(empty, {}, MagicMock())


def test_prepare_qa_ingest_params_from_embed_model():
    kb = SimpleNamespace(
        embed_model=SimpleNamespace(base_url="http://e", api_key="k", model_name="emb"),
        knowledge_index_name=lambda: "idx",
    )
    out = tasks._prepare_qa_ingest_params(kb)
    assert out["knowledge_base_id"] == "idx"
    assert out["embed_model_name"] == "emb"
    assert out["chunk_mode"] == "full"


def test_get_bot_chat_flow_missing_returns_none(db):
    assert tasks._get_bot_chat_flow(999999) is None
