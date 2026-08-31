"""告警指纹纯函数与 AutoCloser 按 external_id 自动关闭契约。"""
import hashlib

import pytest
from django.utils import timezone

from apps.alerts.aggregation.core.fingerprint import generate_fingerprint, validate_dimensions
from apps.alerts.aggregation.recovery.auto_closer import AutoCloser
from apps.alerts.constants.constants import AlertStatus, EventAction
from apps.alerts.models.alert_source import AlertSource
from apps.alerts.models.models import Alert, Event

pytestmark = pytest.mark.django_db


def test_generate_fingerprint_empty_and_sorted_pairs():
    assert generate_fingerprint({}) == hashlib.md5(b"").hexdigest()
    assert generate_fingerprint(None) == hashlib.md5(b"").hexdigest()
    left = generate_fingerprint({"b": "2", "a": "1"})
    right = generate_fingerprint({"a": "1", "b": "2"})
    assert left == right
    assert left == hashlib.md5(b"a:1|b:2").hexdigest()


def test_validate_dimensions_rejects_non_dict_and_blank_or_non_str():
    assert validate_dimensions({"service": "api"}) is True
    assert validate_dimensions("bad") is False
    assert validate_dimensions({"service": 1}) is False
    assert validate_dimensions({1: "api"}) is False
    assert validate_dimensions({"": "api"}) is False
    assert validate_dimensions({"service": ""}) is False


def _source():
    return AlertSource.objects.create(name="ac-src", source_id="ac1", source_type="restful", secret="x")


def _event(source, event_id, **over):
    data = dict(
        source=source,
        raw_data={},
        title="t",
        level="0",
        start_time=timezone.now(),
        event_id=event_id,
        action=EventAction.CREATED,
        external_id="ext-1",
    )
    data.update(over)
    return Event.objects.create(**data)


def test_auto_closer_skips_missing_external_id_and_closes_matching_alert():
    source = _source()
    created = _event(source, "E-created")
    closed = _event(source, "E-closed", action=EventAction.CLOSED)
    no_ext = _event(source, "E-no-ext", action=EventAction.CLOSED, external_id="")
    other = _event(source, "E-other", action=EventAction.CREATED, external_id="ext-other")

    active = Alert.objects.create(
        alert_id="A-active", level="0", title="t", content="c", fingerprint="fp1",
        status=AlertStatus.PENDING,
    )
    active.events.add(created)
    already = Alert.objects.create(
        alert_id="A-closed", level="0", title="t", content="c", fingerprint="fp2",
        status=AlertStatus.CLOSED,
    )
    already.events.add(created)
    stray = Alert.objects.create(
        alert_id="A-other", level="0", title="t", content="c", fingerprint="fp3",
        status=AlertStatus.UNASSIGNED,
    )
    stray.events.add(other)

    AutoCloser.handle_closed_events(Event.objects.filter(id__in=[closed.id, no_ext.id]))
    active.refresh_from_db()
    already.refresh_from_db()
    stray.refresh_from_db()
    assert active.status == AlertStatus.AUTO_CLOSE
    assert already.status == AlertStatus.CLOSED
    assert stray.status == AlertStatus.UNASSIGNED
