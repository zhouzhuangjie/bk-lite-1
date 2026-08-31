"""MetricsInstanceViewSet 查询参数守卫、单位转换与按实例查询鉴权。"""
from types import SimpleNamespace

import pytest
from apps.base.tests.factories import UserFactory
from apps.core.exceptions.base_app_exception import BaseAppException, UnauthorizedException
from apps.monitor.models import MonitorInstance
from apps.monitor.models.monitor_metrics import Metric, MetricGroup
from apps.monitor.models.monitor_object import MonitorObject
from apps.monitor.models.plugin import MonitorPlugin
from apps.monitor.views.metrics_instance import MetricsInstanceViewSet

pytestmark = pytest.mark.django_db


def _vs():
    return MetricsInstanceViewSet()


def test_get_metrics_requires_query_and_converts_unit(monkeypatch):
    with pytest.raises(BaseAppException, match="query is required"):
        _vs().get_metrics(SimpleNamespace(GET={}))

    captured = {}

    def fake_get_metrics(query):
        captured["query"] = query
        return {
            "status": "success",
            "data": {"result": [{"metric": {}, "value": [1, "2048"]}]},
        }

    monkeypatch.setattr("apps.monitor.views.metrics_instance.MetricsService.get_metrics", fake_get_metrics)
    monkeypatch.setattr(
        "apps.monitor.views.metrics_instance.WebUtils.response_success",
        staticmethod(lambda data: data),
    )
    out = _vs().get_metrics(SimpleNamespace(GET={"query": "up", "source_unit": "bytes", "unit": "kibibytes"}))
    assert captured["query"] == "up"
    assert float(out["data"]["result"][0]["value"][1]) == pytest.approx(2.0)
    assert out["data"]["unit"] == "kibibytes"

    auto = _vs().get_metrics(SimpleNamespace(GET={"query": "up", "source_unit": "bytes"}))
    assert "unit" in auto["data"]


def test_get_metrics_range_validates_window_and_step(monkeypatch):
    with pytest.raises(BaseAppException, match="query is required"):
        _vs().get_metrics_range(SimpleNamespace(GET={}))
    with pytest.raises(BaseAppException, match="start and end are required"):
        _vs().get_metrics_range(SimpleNamespace(GET={"query": "up"}))
    with pytest.raises(BaseAppException, match="must be integer"):
        _vs().get_metrics_range(SimpleNamespace(GET={"query": "up", "start": "x", "end": "1"}))
    with pytest.raises(BaseAppException, match="start must be less than end"):
        _vs().get_metrics_range(SimpleNamespace(GET={"query": "up", "start": "10", "end": "10"}))
    with pytest.raises(BaseAppException, match="step is required"):
        _vs().get_metrics_range(SimpleNamespace(GET={"query": "up", "start": "1", "end": "2", "step": ""}))
    with pytest.raises(BaseAppException, match="invalid step"):
        _vs().get_metrics_range(SimpleNamespace(GET={"query": "up", "start": "1", "end": "2", "step": "bad"}))

    monkeypatch.setattr(
        "apps.monitor.views.metrics_instance.MetricsService.get_metrics_range",
        lambda *a, **k: {
            "status": "success",
            "data": {"result": [{"metric": {}, "values": [[1, "1024"]]}]},
        },
    )
    monkeypatch.setattr(
        "apps.monitor.views.metrics_instance.WebUtils.response_success",
        staticmethod(lambda data: data),
    )
    out = _vs().get_metrics_range(
        SimpleNamespace(
            GET={
                "query": "cpu",
                "start": "0",
                "end": "60000",
                "step": "15s",
                "source_unit": "bytes",
                "unit": "kibibytes",
            }
        )
    )
    assert float(out["data"]["result"][0]["values"][0][1]) == pytest.approx(1.0)


def _query_request(user, params=None):
    return SimpleNamespace(GET=params or {}, user=user, COOKIES={"current_team": "1"})


def test_query_by_instance_requires_params_and_metric(monkeypatch):
    user = UserFactory(username="mi-su", domain="domain.com", roles=[], is_superuser=True)
    with pytest.raises(BaseAppException, match="monitor_object_id, metric_id, instance_id are required"):
        _vs().query_by_instance(_query_request(user))

    obj = MonitorObject.objects.create(name="MIObj", level="base")
    request = _query_request(
        user,
        {"monitor_object_id": obj.id, "metric_id": 999999, "instance_id": "('h1',)"},
    )
    with pytest.raises(BaseAppException, match="Metric not found"):
        _vs().query_by_instance(request)


def test_query_by_instance_denies_unauthorized_and_converts(monkeypatch):
    obj = MonitorObject.objects.create(name="MIObj2", level="base")
    plugin = MonitorPlugin.objects.create(name="MIPlugin")
    group = MetricGroup.objects.create(monitor_object=obj, monitor_plugin=plugin, name="g")
    metric = Metric.objects.create(
        monitor_object=obj,
        monitor_plugin=plugin,
        metric_group=group,
        name="mem",
        query="mem{}",
        unit="bytes",
        instance_id_keys=["instance_id"],
    )
    MonitorInstance.objects.create(id="('h1',)", name="h1", monitor_object=obj)

    guest = UserFactory(username="mi-guest", domain="domain.com", roles=[], is_superuser=False)
    request = _query_request(
        guest,
        {"monitor_object_id": obj.id, "metric_id": metric.id, "instance_id": "('h1',)"},
    )
    monkeypatch.setattr(
        "apps.monitor.views.metrics_instance.get_permission_rules",
        lambda *a, **k: {"team": [1], "instance": []},
    )
    monkeypatch.setattr(
        "apps.monitor.views.metrics_instance.permission_filter",
        lambda model, perm, **kw: model.objects.none(),
    )
    with pytest.raises(UnauthorizedException, match="无权访问该监控实例"):
        _vs().query_by_instance(request)

    su = UserFactory(username="mi-su2", domain="domain.com", roles=[], is_superuser=True)
    request = _query_request(
        su,
        {"monitor_object_id": obj.id, "metric_id": metric.id, "instance_id": "('h1',)"},
    )
    monkeypatch.setattr(
        "apps.monitor.views.metrics_instance.MetricsService.get_effective_metric_instance_id_keys",
        lambda m: ["instance_id"],
    )
    monkeypatch.setattr(
        "apps.monitor.views.metrics_instance.MetricsService.query_metric_by_instance",
        lambda **kw: {
            "status": "success",
            "data": {"result": [{"metric": {}, "value": [1, "2048"]}]},
        },
    )
    monkeypatch.setattr(
        "apps.monitor.views.metrics_instance.WebUtils.response_success",
        staticmethod(lambda data: data),
    )
    out = _vs().query_by_instance(request)
    assert float(out["data"]["result"][0]["value"][1]) == pytest.approx(2.0)
    assert out["data"]["unit"] == "kibibytes"
    assert out["data"]["source_unit"] == "bytes"
