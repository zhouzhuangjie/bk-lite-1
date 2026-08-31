"""聚合处理器剩余分支：维度校验、缺失检查、指纹规范化与聚合失败兜底。

对照 spec/prd/告警中心·配置：非法维度必须丢弃；聚合失败不得阻断其它策略。
"""

import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.alerts.aggregation.processor.aggregation_processor import AggregationProcessor
from apps.alerts.constants.constants import (
    AlertStatus,
    EventAction,
    HeartbeatStatus,
    LevelType,
    SessionStatus,
)
from apps.alerts.models.alert_operator import AlarmStrategy
from apps.alerts.models.alert_source import AlertSource
from apps.alerts.models.models import Alert, Event, Level

pytestmark = pytest.mark.django_db


def _source():
    return AlertSource.objects.create(name="r13-src", source_id="r13s", source_type="restful", secret="x")


def _missing_strategy(**param_over):
    params = {
        "check_mode": "cron",
        "cron_expr": "*/5 * * * *",
        "grace_period": 0,
        "activation_mode": "immediate",
        "auto_recovery": True,
        "alert_template": {"title": "心跳缺失", "level": "1", "description": "缺失"},
    }
    params.update(param_over)
    return AlarmStrategy.objects.create(
        name="缺失-r13", strategy_type="missing_detection", is_active=True,
        team=[1], dispatch_team=[1],
        match_rules=[[{"key": "item", "operator": "eq", "value": "heartbeat"}]],
        params=params,
    )


# --------------------------------------------------------------------------
# _validate_dimensions
# --------------------------------------------------------------------------


def test_validate_dimensions_empty_falls_back_to_event_id():
    assert AggregationProcessor._validate_dimensions([], "s") == ["event_id"]
    assert AggregationProcessor._validate_dimensions(None, "s") == ["event_id"]


def test_validate_dimensions_skips_non_string_illegal_and_unknown():
    """非字符串、格式非法、不在白名单的维度一律跳过；全无效则回退 event_id。"""
    result = AggregationProcessor._validate_dimensions(
        [123, "bad-name!", "not_a_real_dim", "service"],
        "策略A",
    )
    assert result == ["service"]

    assert AggregationProcessor._validate_dimensions([1, "??"], "策略B") == ["event_id"]


# --------------------------------------------------------------------------
# process_aggregation / _process_strategy 异常
# --------------------------------------------------------------------------


def test_process_aggregation_reraises_and_closes_connection():
    proc = AggregationProcessor()
    with (
        patch.object(proc, "_get_active_strategies", side_effect=RuntimeError("db down")),
        patch.object(proc.db_conn, "close") as closed,
    ):
        with pytest.raises(RuntimeError, match="db down"):
            proc.process_aggregation()
    closed.assert_called_once()


def test_process_strategy_swallows_inner_exception():
    """单策略异常只记日志，不得向外抛。"""
    strategy = AlarmStrategy.objects.create(
        name="降噪-r13", strategy_type="smart_denoise", is_active=True,
        team=[1], dispatch_team=[1], params={"window_size": 60},
    )
    proc = AggregationProcessor()
    with (
        patch.object(proc, "get_events_for_strategy", side_effect=RuntimeError("query boom")),
        patch("apps.alerts.aggregation.processor.aggregation_processor.logger") as mock_logger,
    ):
        proc._process_strategy(strategy, timezone.now())
    mock_logger.exception.assert_called_once()
    assert mock_logger.exception.call_args.args[0] == "[AlertAggregation] 策略 %s 处理失败"
    assert mock_logger.exception.call_args.args[1] == "降噪-r13"


# --------------------------------------------------------------------------
# missing_detection：已有活跃告警跳过 / 触发 / 恢复无告警
# --------------------------------------------------------------------------


def test_missing_detection_skips_duplicate_when_active_alert_exists():
    from apps.alerts.aggregation.builder.synthetic_alert_builder import SyntheticAlertBuilder

    strategy = _missing_strategy()
    AlarmStrategy.objects.filter(pk=strategy.pk).update(
        created_at=timezone.now() - datetime.timedelta(hours=3),
    )
    strategy.refresh_from_db()
    active = SyntheticAlertBuilder.create_alert(strategy, strategy.params, timezone.now())
    assert active.status in AlertStatus.ACTIVATE_STATUS

    AggregationProcessor().process_aggregation()
    strategy.refresh_from_db()
    assert strategy.params.get("heartbeat_status") == HeartbeatStatus.ALERTING
    assert Alert.objects.filter(rule_id=str(strategy.id)).count() == 1


def test_missing_detection_triggers_when_deadline_passed():
    strategy = _missing_strategy()
    AlarmStrategy.objects.filter(pk=strategy.pk).update(
        created_at=timezone.now() - datetime.timedelta(hours=3),
    )
    with patch.object(AggregationProcessor, "_schedule_auto_assignment"):
        AggregationProcessor().process_aggregation()
    strategy.refresh_from_db()
    assert strategy.params.get("heartbeat_status") == HeartbeatStatus.ALERTING
    assert Alert.objects.filter(rule_id=str(strategy.id)).exists()


def test_missing_detection_exception_reraises():
    strategy = _missing_strategy()
    proc = AggregationProcessor()
    with patch.object(proc, "_load_params", side_effect=RuntimeError("params fail")):
        with pytest.raises(RuntimeError, match="params fail"):
            proc._process_missing_detection_strategy(strategy, timezone.now())


def test_recover_missing_alert_returns_none_without_active():
    strategy = _missing_strategy()
    proc = AggregationProcessor()
    assert proc._recover_missing_alert(strategy, strategy.params, timezone.now()) is None


# --------------------------------------------------------------------------
# _calculate_deadline
# --------------------------------------------------------------------------


def test_calculate_deadline_invalid_cron_reraises():
    from croniter.croniter import CroniterBadCronError

    strategy = _missing_strategy(cron_expr="not-a-cron")
    proc = AggregationProcessor()
    with pytest.raises(CroniterBadCronError):
        proc._calculate_deadline(strategy, strategy.params, timezone.now())


def test_calculate_deadline_uses_next_slot_when_heartbeat_fresh():
    """上次心跳晚于上一 cron 点时，deadline 取下一周期 + grace。"""
    now = timezone.now()
    strategy = _missing_strategy(grace_period=2)
    params = dict(strategy.params)
    params["last_heartbeat_time"] = (now - datetime.timedelta(minutes=1)).isoformat()
    params["activation_mode"] = "first_heartbeat"
    proc = AggregationProcessor()
    deadline = proc._calculate_deadline(strategy, params, now)
    assert deadline is not None
    assert deadline > now


def test_calculate_deadline_returns_none_when_first_expected_normalize_fails():
    strategy = _missing_strategy()
    proc = AggregationProcessor()
    real_norm = AggregationProcessor._normalize_to_project_timezone

    def _norm(value, project_tz=None):
        # croniter.get_next 之后的第一次「期望时间」规范化返回 None
        if value is not None and getattr(value, "tzinfo", None) == AggregationProcessor.HEARTBEAT_CRON_SOURCE_TIMEZONE:
            return None
        return real_norm(value, project_tz)

    with patch.object(AggregationProcessor, "_normalize_to_project_timezone", side_effect=_norm):
        assert proc._calculate_deadline(strategy, strategy.params, timezone.now()) is None


# --------------------------------------------------------------------------
# 时间解析
# --------------------------------------------------------------------------


def test_parse_runtime_datetime_falls_back_to_fromisoformat():
    """Django parse_datetime 失败时走 fromisoformat。"""
    with patch(
        "apps.alerts.aggregation.processor.aggregation_processor.parse_datetime",
        return_value=None,
    ):
        result = AggregationProcessor._parse_runtime_datetime("2026-01-01T10:00:00")
    assert result.year == 2026
    assert result.month == 1
    assert timezone.is_aware(result)


def test_normalize_to_timezone_makes_naive_aware():
    naive = datetime.datetime(2026, 1, 1, 10, 0, 0)
    tz = ZoneInfo("Asia/Shanghai")
    result = AggregationProcessor._normalize_to_timezone(naive, tz)
    assert timezone.is_aware(result)
    assert result.tzinfo == tz


# --------------------------------------------------------------------------
# _aggregate_for_dimensions / _create_or_update_alerts
# --------------------------------------------------------------------------


def test_aggregate_skips_when_load_fails_and_marks_executed():
    strategy = AlarmStrategy.objects.create(
        name="agg-empty", strategy_type="smart_denoise", is_active=True,
        team=[1], dispatch_team=[1], params={"window_size": 60},
    )
    proc = AggregationProcessor()
    with patch.object(proc.db_conn, "load_events_to_memory", return_value=None):
        assert proc._aggregate_for_dimensions(strategy, Event.objects.none(), ["service"], timezone.now()) is False
    strategy.refresh_from_db()
    assert strategy.last_execute_time is not None


def test_aggregate_empty_results_marks_executed():
    strategy = AlarmStrategy.objects.create(
        name="agg-no-rows", strategy_type="smart_denoise", is_active=True,
        team=[1], dispatch_team=[1], params={"window_size": 60},
    )
    proc = AggregationProcessor()
    with (
        patch.object(proc.db_conn, "load_events_to_memory", return_value=True),
        patch(
            "apps.alerts.aggregation.processor.aggregation_processor.WindowFactory.create_from_strategy",
            return_value=SimpleNamespace(window_type="sliding", window_size_minutes=60),
        ),
        patch.object(proc.sql_builder, "build_aggregation_sql", return_value="SELECT 1"),
        patch.object(proc.db_conn, "execute_query", return_value=[]),
    ):
        assert proc._aggregate_for_dimensions(strategy, Event.objects.none(), ["service"], timezone.now()) is False
    strategy.refresh_from_db()
    assert strategy.last_execute_time is not None


def test_aggregate_exception_returns_false():
    strategy = AlarmStrategy.objects.create(
        name="agg-boom", strategy_type="smart_denoise", is_active=True,
        team=[1], dispatch_team=[1], params={"window_size": 60},
    )
    proc = AggregationProcessor()
    with patch.object(proc.db_conn, "load_events_to_memory", side_effect=RuntimeError("duckdb")):
        assert proc._aggregate_for_dimensions(strategy, Event.objects.none(), ["service"], timezone.now()) is False


def test_create_or_update_alerts_delays_observing_session_and_swallows_row_error():
    """观察期会话告警不得进入自动分派；单行失败不阻断其它行。"""
    strategy = AlarmStrategy.objects.create(
        name="agg-obs", strategy_type="smart_denoise", is_active=True,
        team=[1], dispatch_team=[1], params={"window_size": 60},
    )
    observing = SimpleNamespace(
        alert_id="ALERT-OBS",
        is_session_alert=True,
        session_status=SessionStatus.OBSERVING,
    )
    proc = AggregationProcessor()
    rows = [
        {"fingerprint": "fp-obs", "alert_level": "1"},
        {"fingerprint": "fp-boom", "alert_level": "1"},
    ]

    def _create(aggregation_result, strategy, group_by_field):
        if aggregation_result["fingerprint"] == "fp-boom":
            raise RuntimeError("builder fail")
        return observing

    with (
        patch.object(AggregationProcessor, "_normalize_fingerprint"),
        patch.object(AggregationProcessor, "_is_existing_alert", return_value=False),
        patch(
            "apps.alerts.aggregation.processor.aggregation_processor.AlertBuilder.create_or_update_alert",
            side_effect=_create,
        ),
        patch(
            "apps.alerts.aggregation.processor.aggregation_processor.AlertRecoveryChecker.check_and_recover_alert",
            return_value=False,
        ),
        patch.object(AggregationProcessor, "_schedule_auto_assignment") as scheduled,
    ):
        count = proc._create_or_update_alerts(rows, strategy, ["service"])
    assert count == 1
    scheduled.assert_not_called()


# --------------------------------------------------------------------------
# _normalize_fingerprint
# --------------------------------------------------------------------------


def test_normalize_fingerprint_noop_without_fingerprint():
    result = {"alert_level": "0"}
    AggregationProcessor._normalize_fingerprint(result, [{"level_id": 0}])
    assert "fingerprint" not in result


def test_normalize_fingerprint_without_alert_levels_hashes_raw():
    from apps.alerts.utils.util import str_to_md5

    result = {"fingerprint": "crit|host-a cpu", "alert_level": "0", "alert_description": "d"}
    AggregationProcessor._normalize_fingerprint(result, [])
    assert result["fingerprint"] == str_to_md5("host-a cpu")
