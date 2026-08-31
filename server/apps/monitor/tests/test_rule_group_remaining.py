"""RuleGrouping：缺指标、查询失败、条件/选择规则与分组更新。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.monitor.tasks.services.rule_group import RuleGrouping

pytestmark = pytest.mark.django_db


def test_get_query_missing_metric_and_exception():
    with patch("apps.monitor.tasks.services.rule_group.Metric.objects.filter") as filt:
        filt.return_value.first.return_value = None
        assert RuleGrouping.get_query({"metric_id": 9, "filter": []}) is None

    metric = SimpleNamespace(query="up{__$labels__}")
    with patch("apps.monitor.tasks.services.rule_group.Metric.objects.filter") as filt, patch(
        "apps.monitor.tasks.services.rule_group.format_to_vm_filter",
        return_value='job="node",',
    ):
        filt.return_value.first.return_value = metric
        assert RuleGrouping.get_query({"metric_id": 1, "filter": [{"k": "v"}]}) == 'up{job="node"}'

    with patch("apps.monitor.tasks.services.rule_group.Metric.objects.filter", side_effect=RuntimeError("db")):
        assert RuleGrouping.get_query({"metric_id": 1}) is None


def test_get_asso_by_condition_rule_skips_unknown_object_and_maps_instances(monkeypatch):
    rule = SimpleNamespace(
        id=3,
        monitor_object=SimpleNamespace(name="Host"),
        monitor_object_id=8,
        rule={"metric_id": 1},
        organizations=[7],
    )
    monkeypatch.setattr(
        "apps.monitor.tasks.services.rule_group.MonitorObject.objects.all",
        lambda: SimpleNamespace(values=lambda *a: []),
    )
    assert RuleGrouping.get_asso_by_condition_rule(rule) == []

    monkeypatch.setattr(
        "apps.monitor.tasks.services.rule_group.MonitorObject.objects.all",
        lambda: SimpleNamespace(values=lambda *a: [{"name": "Host", "instance_id_keys": ["instance"]}]),
    )
    monkeypatch.setattr(
        "apps.monitor.tasks.services.rule_group.MonitorInstance.objects.filter",
        lambda **k: SimpleNamespace(values_list=lambda *a, **kw: ["('h1',)"]),
    )
    monkeypatch.setattr(RuleGrouping, "get_query", staticmethod(lambda r: None))
    assert RuleGrouping.get_asso_by_condition_rule(rule) == []

    monkeypatch.setattr(RuleGrouping, "get_query", staticmethod(lambda r: "up"))
    monkeypatch.setattr(
        "apps.monitor.tasks.services.rule_group.VictoriaMetricsAPI",
        lambda: SimpleNamespace(query=lambda q, step="10m": {"data": {"result": [{"metric": {"instance": "h1"}}]}}),
    )
    assert RuleGrouping.get_asso_by_condition_rule(rule) == [("('h1',)", 7)]


def test_get_asso_by_select_rule_filters_deleted_and_swallows_errors(monkeypatch):
    grouping = RuleGrouping.__new__(RuleGrouping)
    rule = SimpleNamespace(
        id=4,
        monitor_object_id=8,
        grouping_rules={"instances": ["('keep',)", "('gone',)"]},
        organizations=[2],
    )
    monkeypatch.setattr(
        "apps.monitor.tasks.services.rule_group.MonitorInstance.objects.filter",
        lambda **k: SimpleNamespace(values_list=lambda *a, **kw: ["('keep',)"]),
    )
    assert grouping.get_asso_by_select_rule(rule) == [("('keep',)", 2)]

    def _raise(**k):
        raise RuntimeError("db")

    monkeypatch.setattr(
        "apps.monitor.tasks.services.rule_group.MonitorInstance.objects.filter",
        _raise,
    )
    assert grouping.get_asso_by_select_rule(rule) == []


def test_update_grouping_creates_missing_associations(monkeypatch):
    rule = SimpleNamespace(id=1)
    grouping = RuleGrouping.__new__(RuleGrouping)
    grouping.rules = [rule]
    monkeypatch.setattr(RuleGrouping, "get_asso_by_condition_rule", staticmethod(lambda r: [("('h1',)", 3)]))
    existing = SimpleNamespace(monitor_instance_id="('h0',)", organization=1, id=99)
    created = []

    class _OrgQS:
        def all(self):
            return [existing]

    monkeypatch.setattr(
        "apps.monitor.tasks.services.rule_group.MonitorInstanceOrganization.objects",
        SimpleNamespace(
            all=lambda: [existing],
            bulk_create=lambda objs, batch_size=None, ignore_conflicts=False: created.extend(objs),
        ),
    )
    grouping.update_grouping()
    assert len(created) == 1
    assert created[0].monitor_instance_id == "('h1',)"
    assert created[0].organization == 3
