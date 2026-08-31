"""IPAM 对账 IO：空子网跳过、图查询加载、更新路径、关联幂等与利用率回写。"""
from unittest.mock import MagicMock, patch

import pytest

from apps.cmdb.services import ipam_reconcile
from apps.core.exceptions.base_app_exception import BaseAppException

pytestmark = pytest.mark.unit


def test_match_subnet_skips_empty_address_and_mask():
    subnets = [
        {"subnet_address": "", "subnet_mask": "24"},
        {"subnet_address": "10.0.1.0", "subnet_mask": ""},
        {"subnet_address": "10.0.1.0", "subnet_mask": None},
        {"_id": 9, "subnet_address": "10.0.1.0", "subnet_mask": "24"},
    ]
    assert ipam_reconcile.match_subnet_for_ip("10.0.1.8", subnets)["_id"] == 9


def test_load_helpers_query_graph_and_skip_blank_ips():
    sources = MagicMock()
    sources.filter.return_value.values.return_value = [{"model_id": "host", "ip_attr_id": "ip_addr"}]
    graph = MagicMock()
    graph.__enter__.return_value = graph
    graph.__exit__.return_value = False
    graph.query_entity.return_value = (
        [
            {"_id": 1, "model_id": "host", "ip_addr": "10.0.1.1", "inst_name": "h1"},
            {"_id": 2, "model_id": "host", "ip_addr": "", "inst_name": "blank"},
        ],
        None,
    )
    with (
        patch("apps.cmdb.models.ipam_models.IPAMReconcileSource.objects", sources),
        patch("apps.cmdb.services.ipam_reconcile.GraphClient", return_value=graph),
    ):
        assert ipam_reconcile._load_sources() == [{"model_id": "host", "ip_attr_id": "ip_addr"}]
        assert ipam_reconcile._load_subnets() == graph.query_entity.return_value[0]
        cis = ipam_reconcile._load_ci_with_ip("host", "ip_addr")
        assert cis == [{"_id": 1, "model_id": "host", "ip_addr": "10.0.1.1", "inst_name": "h1"}]
        graph.query_entity.return_value = ([], None)
        assert ipam_reconcile._load_existing_ips() == []


def test_upsert_existing_updates_and_create_uses_new_id():
    from apps.cmdb.services.instance import InstanceManage

    with (
        patch.object(InstanceManage, "instance_update", return_value=None) as updated,
        patch.object(InstanceManage, "instance_create", return_value={"_id": 77}) as created,
        patch.object(ipam_reconcile, "_ensure_associations") as assoc,
    ):
        out = ipam_reconcile._upsert_ip_instance(
            existing_id=12,
            subnet_id=3,
            ip_addr="10.0.1.9",
            ip_status="online",
            occupants=["host:1"],
        )
        assert out == {"_id": 12}
        updated.assert_called_once()
        assert updated.call_args.args[2] == 12
        assert updated.call_args.args[3]["subnet_id"] == "3"
        created.assert_not_called()
        assoc.assert_called_once_with(12, 3, ["host:1"])

        out = ipam_reconcile._upsert_ip_instance(subnet_id=3, ip_addr="10.0.1.10", ip_status="conflict")
        assert out == {"_id": 77}
        created.assert_called_once()


def test_ensure_associations_ignores_repetition_and_warns_other_errors(caplog):
    from apps.cmdb.services.instance import InstanceManage

    def create(data, operator):
        if data["asst_id"] == "group":
            raise BaseAppException("association repetition")
        raise BaseAppException("association not found")

    with patch.object(InstanceManage, "instance_association_create", side_effect=create):
        ipam_reconcile._ensure_associations(900, 1, ["host:55"])
    warnings = [rec.getMessage() for rec in caplog.records if rec.levelname == "WARNING"]
    assert any("association not found" in msg for msg in warnings)
    assert not any("repetition" in msg for msg in warnings)


def test_mark_offline_and_writeback_skips_missing_subnet():
    from apps.cmdb.services.instance import InstanceManage

    graph = MagicMock()
    graph.__enter__.return_value = graph
    graph.__exit__.return_value = False
    graph.query_entity.return_value = ([{"_id": 1}, {"_id": 2}], None)

    with patch.object(InstanceManage, "instance_update") as updated:
        ipam_reconcile._mark_offline(44)
        updated.assert_called_once()
        assert updated.call_args.args[2] == 44
        assert updated.call_args.args[3] == {"ip_status": ["offline"]}

    with (
        patch.object(InstanceManage, "query_entity_by_id", side_effect=[None, {"subnet_address": "10.0.1.0", "subnet_mask": "24"}]),
        patch.object(InstanceManage, "instance_update") as updated,
        patch("apps.cmdb.services.ipam_reconcile.GraphClient", return_value=graph),
    ):
        ipam_reconcile._writeback_subnet_utilization([1, 2])
        updated.assert_called_once()
        payload = updated.call_args.args[3]
        assert payload["subnet_used_size"] == 2
        assert payload["subnet_available_size"] == payload["subnet_size"] - 2


def test_run_reconciliation_updates_conflict_and_skips_unmatched_ci(monkeypatch):
    monkeypatch.setattr(ipam_reconcile, "_load_sources", lambda: [{"model_id": "host", "ip_attr_id": "ip_addr"}])
    monkeypatch.setattr(
        ipam_reconcile,
        "_load_subnets",
        lambda: [{"_id": 1, "subnet_address": "10.0.1.0", "subnet_mask": "24", "organization": [8]}],
    )
    monkeypatch.setattr(
        ipam_reconcile,
        "_load_ci_with_ip",
        lambda model_id, attr: [
            {"_id": 1, "model_id": "host", "ip_addr": "10.0.1.10", "inst_name": "a"},
            {"_id": 2, "model_id": "host", "ip_addr": "10.0.1.10", "inst_name": "b"},
            {"_id": 3, "model_id": "host", "ip_addr": "192.168.0.1", "inst_name": "out"},
        ],
    )
    monkeypatch.setattr(
        ipam_reconcile,
        "_load_existing_ips",
        lambda: [{"_id": 800, "ip_addr": "10.0.1.10", "subnet_id": "1", "auto_collect": True}],
    )
    upserts = []
    monkeypatch.setattr(ipam_reconcile, "_upsert_ip_instance", lambda **kw: upserts.append(kw) or {"_id": 800})
    monkeypatch.setattr(ipam_reconcile, "_writeback_subnet_utilization", lambda s: None)
    monkeypatch.setattr(ipam_reconcile, "_mark_offline", lambda ip_id: None)
    result = ipam_reconcile.run_reconciliation()
    assert result["updated"] == 1
    assert result["conflicts"] == 1
    assert result["created"] == 0
    assert upserts[0]["existing_id"] == 800
    assert upserts[0]["ip_status"] == "conflict"
    assert upserts[0]["organization"] == [8]
