"""LogPolicyScan 剩余：命中计数、分组样本失败、通知内容与空通知。"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from apps.log.tasks.services.policy_scan import LogPolicyScan


def _policy(**overrides):
    base = dict(
        id=13,
        name="scan-r13",
        alert_name="告警",
        alert_type="keyword",
        alert_level="warning",
        alert_condition={"query": "error", "group_by": ["host"]},
        period={"type": "min", "value": 5},
        collect_type=None,
        log_groups=[],
        notice=True,
        notice_users=["alice"],
        notice_type_id=1,
        last_run_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _scan(**overrides):
    return LogPolicyScan(_policy(**overrides))


def test_get_keyword_match_count_empty_invalid_and_numeric():
    scan = _scan()
    scan.vlogs_api = SimpleNamespace(query=lambda **k: [])
    assert scan._get_keyword_match_count("error", 1, 2) == 0

    scan.vlogs_api = SimpleNamespace(query=lambda **k: [{"total_count": "x"}])
    assert scan._get_keyword_match_count("error", 1, 2) == 0

    scan.vlogs_api = SimpleNamespace(query=lambda **k: [{"total_count": "12.8"}])
    assert scan._get_keyword_match_count("error", 1, 2) == 12


def test_fetch_group_sample_swallows_query_error():
    scan = _scan()

    def boom(**kwargs):
        raise RuntimeError("vlogs down")

    scan.vlogs_api = SimpleNamespace(query=boom)
    idx, event = scan._fetch_group_sample(0, {"host": "web"}, 3, "error", 1, 2, 5, ["host"])
    assert idx == 0
    assert event["value"] == 3
    assert event["raw_data"] == []
    assert event["source_id"]


def test_keyword_grouped_skips_incomplete_and_zero(mocker):
    scan = _scan()
    scan.vlogs_api = SimpleNamespace(
        query=lambda **k: [
            {"host": "", "total_count": 4},
            {"host": "web", "total_count": 0},
            {"host": "db", "total_count": 2},
        ]
    )
    mocker.patch.object(scan, "_fetch_group_sample", side_effect=lambda idx, *a, **k: (idx, {"source_id": f"g{idx}"}))
    events = scan._keyword_grouped_alert_detection("error", ["host"], 3, 1, 2)
    assert events == [{"source_id": "g2"}]


def test_format_notice_content_contains_policy_and_link():
    scan = _scan()
    event = SimpleNamespace(event_time="2026-01-01 00:00:00", content="too many errors")
    title, content = scan._format_notice_content(event)
    assert title == "【日志告警通知】"
    assert "告警内容：too many errors" in content
    assert "策略名称：scan-r13" in content
    assert "/log/event/alert" in content
    assert 'href="' in content
    assert 'f"' not in content


def test_send_notice_returns_false_without_users():
    scan = _scan(notice_users=[])
    ok, result = scan.send_notice(SimpleNamespace(content="x", event_time="t"))
    assert ok is False
    assert result == []


def test_notice_skips_when_disabled_or_empty():
    scan = _scan(notice=False)
    assert scan.notice([]) is None
    assert scan.notice([SimpleNamespace(level="warning")]) is None
