"""DuckDuckGo 搜索工具：单条格式化、缺字段默认文案、异常回传、批量隔离失败。"""
from unittest.mock import patch

import pytest

from apps.opspilot.metis.llm.tools.search import duckduckgo as ddg

pytestmark = pytest.mark.unit
CONFIG = {"configurable": {"user_id": "u-1"}}


class _FakeDDGS:
    def __init__(self, results=None, error=None):
        self._results = results or []
        self._error = error

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def text(self, query, max_results=None):
        if self._error:
            raise self._error
        return self._results


def test_duckduckgo_search_formats_hits_and_defaults_missing_fields():
    fake = _FakeDDGS(
        [
            {"title": "文档", "body": "摘要", "href": "https://example.com/a"},
            {},
        ]
    )
    with patch.object(ddg, "DDGS", return_value=fake):
        out = ddg.duckduckgo_search.func(query="bk-lite", max_results=2, config=CONFIG)
    assert "1. 文档\n   摘要\n   链接: https://example.com/a\n" in out
    assert "2. 无标题\n   无内容\n   链接: 无链接\n" in out


def test_duckduckgo_search_returns_exception_text_on_failure():
    with patch.object(ddg, "DDGS", return_value=_FakeDDGS(error=RuntimeError("rate limited"))):
        out = ddg.duckduckgo_search.func(query="q", max_results=1, config=CONFIG)
    assert out == "rate limited"


def test_duckduckgo_search_batch_isolates_per_query_failure():
    calls = {"n": 0}

    def _factory():
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeDDGS([{"title": "ok", "body": "b", "href": "http://x"}])
        return _FakeDDGS(error=ValueError("blocked"))

    with patch.object(ddg, "DDGS", side_effect=_factory):
        out = ddg.duckduckgo_search_batch.func(queries=["a", "b"], max_results=3, config=CONFIG)
    assert out["total"] == 2
    assert out["succeeded"] == 1
    assert out["failed"] == 1
    assert out["results"][0] == {
        "input": "a",
        "ok": True,
        "data": [{"title": "ok", "body": "b", "href": "http://x"}],
    }
    assert out["results"][1] == {"input": "b", "ok": False, "error": "blocked"}
