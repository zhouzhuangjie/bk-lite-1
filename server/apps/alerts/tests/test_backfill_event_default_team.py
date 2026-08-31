"""回填空 team 历史事件到默认组织 [1]。"""
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.alerts.models.alert_source import AlertSource
from apps.alerts.models.models import Event

pytestmark = pytest.mark.django_db


def _event(source, event_id, team):
    return Event.objects.create(
        source=source,
        raw_data={},
        title="t",
        level="0",
        start_time=timezone.now(),
        event_id=event_id,
        team=team,
    )


def test_backfill_event_default_team_dry_run_does_not_write():
    source = AlertSource.objects.create(name="bf-src", source_id="bf1", source_type="restful", secret="x")
    empty = _event(source, "E-empty", [])
    kept = _event(source, "E-kept", [2])
    out = StringIO()
    call_command("backfill_event_default_team", "--dry-run", "--batch-size", "1", stdout=out)
    text = out.getvalue()
    assert f"[DRY-RUN] event={empty.event_id} team=[1]" in text
    assert f"event={kept.event_id}" not in text
    assert "dry_run=True" in text
    empty.refresh_from_db()
    kept.refresh_from_db()
    assert empty.team == []
    assert kept.team == [2]


def test_backfill_event_default_team_updates_empty_only():
    source = AlertSource.objects.create(name="bf-src2", source_id="bf2", source_type="restful", secret="x")
    empty = _event(source, "E-empty2", [])
    kept = _event(source, "E-kept2", [9])
    out = StringIO()
    call_command("backfill_event_default_team", stdout=out)
    empty.refresh_from_db()
    kept.refresh_from_db()
    assert empty.team == [1]
    assert kept.team == [9]
    assert "updated=1" in out.getvalue()
    assert "dry_run=False" in out.getvalue()
