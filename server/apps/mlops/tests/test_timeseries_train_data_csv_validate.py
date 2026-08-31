"""时间序列训练数据 CSV 校验：缺列、空值、无效格式。"""
import io
import types

import pytest
from rest_framework import serializers

from apps.mlops.serializers.timeseries_predict import TimeSeriesPredictTrainDataSerializer
from .conftest import make_serializer_context

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _ctx(monkeypatch, user):
    ctx = make_serializer_context(monkeypatch, user)
    ctx["request"] = types.SimpleNamespace(
        user=user,
        COOKIES={"current_team": "1"},
        query_params={},
    )
    return ctx


def test_timeseries_validate_train_data_rejects_missing_columns_and_nulls(monkeypatch, mlops_user):
    ser = TimeSeriesPredictTrainDataSerializer(context=_ctx(monkeypatch, mlops_user))
    with pytest.raises(serializers.ValidationError) as missing:
        ser.validate_train_data(io.BytesIO(b"a,b\n1,2\n"))
    msg = str(missing.value.detail[0])
    assert msg.startswith("缺少必需列:")
    assert "timestamp" in msg
    assert "value" in msg

    with pytest.raises(serializers.ValidationError) as nulls:
        ser.validate_train_data(io.BytesIO(b"timestamp,value\n2026-01-01,\n"))
    assert str(nulls.value.detail[0]) == "'value'列包含空值"


def test_timeseries_validate_train_data_rejects_invalid_csv(monkeypatch, mlops_user):
    ser = TimeSeriesPredictTrainDataSerializer(context=_ctx(monkeypatch, mlops_user))
    with pytest.raises(serializers.ValidationError) as exc:
        ser.validate_train_data(io.BytesIO(b"timestamp,value\n\"unclosed"))
    assert str(exc.value.detail[0]).startswith("无效的CSV格式:")
