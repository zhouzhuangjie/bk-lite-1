"""数据源视图纯辅助：时间解析、预览配置、下游失败状态映射。"""
from datetime import datetime

import pytest
from rest_framework import status

from apps.operation_analysis.views import datasource_view as dv

pytestmark = pytest.mark.unit


def test_normalize_preview_limit_and_config():
    assert dv._normalize_preview_limit(None) == 100
    assert dv._normalize_preview_limit(5) == 5
    assert dv._normalize_preview_limit(99999) == 1000
    with pytest.raises(ValueError, match="整数"):
        dv._normalize_preview_limit("x")

    assert dv._normalize_preview_config({"a": 1}) == {"a": 1}
    assert dv._normalize_preview_config("") == {}
    assert dv._normalize_preview_config('{"k": 2}') == {"k": 2}
    assert dv._normalize_preview_config("{bad") == {}
    assert dv._normalize_preview_config("[1]") == {}
    assert dv._normalize_preview_config(12) == {}


def test_parse_time_value_datetime_timestamp_and_iso():
    now = datetime(2026, 4, 19, 9, 34, 13)
    assert dv._parse_time_value(now) is now
    ts = dv._parse_time_value(1713519253)
    assert isinstance(ts, datetime)
    millis = dv._parse_time_value(1713519253000)
    assert abs((millis - ts).total_seconds()) < 2
    iso = dv._parse_time_value("2026-04-19T09:34:13")
    assert iso == datetime(2026, 4, 19, 9, 34, 13)
    plain = dv._parse_time_value("2026-04-19 09:34:13")
    assert plain == datetime(2026, 4, 19, 9, 34, 13)
    with pytest.raises(ValueError, match="不能为空"):
        dv._parse_time_value("  ")
    with pytest.raises(ValueError, match="时间格式错误"):
        dv._parse_time_value("19/04/2026")


def test_normalize_time_range_minutes_and_pair():
    minutes = dv._normalize_time_range(30)
    assert len(minutes) == 2
    start = datetime.strptime(minutes[0], dv.TIME_RANGE_FORMAT)
    end = datetime.strptime(minutes[1], dv.TIME_RANGE_FORMAT)
    assert (end - start).total_seconds() == pytest.approx(30 * 60, abs=2)
    with pytest.raises(ValueError, match="正整数"):
        dv._normalize_time_range(0)

    pair = dv._normalize_time_range(["2026-04-19 09:00:00", "2026-04-19 10:00:00"])
    assert pair[0] == "2026-04-19 09:00:00"
    assert pair[1] == "2026-04-19 10:00:00"
    with pytest.raises(ValueError, match="开始时间必须小于结束时间"):
        dv._normalize_time_range(["2026-04-19 10:00:00", "2026-04-19 09:00:00"])
    mapped = dv._normalize_time_range({"start": "2026-04-19 09:00:00", "end": "2026-04-19 09:05:00"})
    assert mapped[1] == "2026-04-19 09:05:00"
    with pytest.raises(ValueError, match="参数格式错误"):
        dv._normalize_time_range("last-hour")


def test_downstream_failure_status_maps_code_and_message():
    assert dv._get_downstream_failure_status({"code": 403}) == 403
    assert dv._get_downstream_failure_status({"code": 40400}) == 404
    assert dv._get_downstream_failure_status({"message": "无权访问"}) == status.HTTP_403_FORBIDDEN
    assert dv._get_downstream_failure_status({"message": "资源不存在"}) == status.HTTP_404_NOT_FOUND
    assert dv._get_downstream_failure_status({"message": "参数错误"}) == status.HTTP_400_BAD_REQUEST
    assert dv._get_downstream_failure_status({"message": "timeout"}) == status.HTTP_502_BAD_GATEWAY


def test_normalize_downstream_result_wraps_non_dict_payload():
    assert dv._normalize_downstream_result({"result": False, "data": 1})["result"] is False
    wrapped = dv._normalize_downstream_result([1, 2])
    assert wrapped == {"result": True, "data": [1, 2], "message": ""}
