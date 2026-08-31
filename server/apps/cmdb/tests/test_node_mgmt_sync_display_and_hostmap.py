"""NodeMgmtSyncService 展示载荷 / 主机映射 / OS 归一化 / 任务修复契约。

仅 mock ModelManage / InstanceManage / CollectModelService 图与下发边界。
锁定：
- get_task 修复空 name / 非内置标记；
- _load_existing_host_map / _query_region_host_instances 跳过非法行；
- _map_host_os_type 枚举命中与关键字回退；
- 采集展示：raw_data 回填、last_time、list_collect_items；
- get_display_payload 自动采集 / 同步回退 / 空态；
- trigger_sync / trigger_collect 委托。
"""
import pydantic.root_model  # noqa

from datetime import datetime
from types import SimpleNamespace

import pytest

from apps.cmdb.constants.constants import CollectPluginTypes, CollectRunStatusType
from apps.cmdb.models.collect_model import CollectModels
from apps.cmdb.models.node_mgmt_sync import NodeMgmtSyncConfig, NodeMgmtSyncRun
from apps.cmdb.services.node_mgmt_sync_service import NodeMgmtSyncService as S

pytestmark = pytest.mark.django_db


def _collect_task(**kw):
    defaults = dict(
        name=kw.pop("name", "nm-collect"),
        task_type=CollectPluginTypes.HOST,
        model_id="host",
        cycle_value_type="cycle",
        is_system=True,
        is_visible=False,
        system_code=S._system_code(1),
        team=[1],
        exec_status=CollectRunStatusType.SUCCESS,
    )
    defaults.update(kw)
    return CollectModels.objects.create(**defaults)


class TestGetTaskRepair:
    def test_空名称与非内置会被写回(self):
        NodeMgmtSyncConfig.objects.all().delete()
        task = NodeMgmtSyncConfig.objects.create(name="", is_builtin=False)
        out = S.get_task()
        assert out.id == task.id
        out.refresh_from_db()
        assert out.name == S.TASK_NAME
        assert out.is_builtin is True


class TestNormalizeRemaining:
    pytestmark = pytest.mark.unit

    def test_detail_bucket_data非列表视为空(self):
        out = S._normalize_detail_bucket({"data": "not-a-list"})
        assert out == {"data": [], "count": 0}

    def test_message写入last_time(self):
        msg = S._normalize_display_message({"last_time": "2026-01-02 03:04:05"})
        assert msg["last_time"] == "2026-01-02 03:04:05"

    def test_serialize_dt_naive补时区(self):
        naive = datetime(2026, 6, 1, 12, 0, 0)
        text = S._serialize_dt(naive)
        assert text is not None
        assert text.startswith("2026-06-01 12:00:00")


class TestLoadExistingHostMap:
    def test_attrs为字符串且无实例返回空(self, mocker):
        mocker.patch(
            "apps.cmdb.services.node_mgmt_sync_service.ModelManage.search_model_info",
            return_value={"attrs": "bad"},
        )
        mocker.patch(
            "apps.cmdb.services.node_mgmt_sync_service.InstanceManage.search_inst",
            return_value=([], 0),
        )
        assert S._load_existing_host_map(0) == {}

    def test_跳过无ip或无cloud并按元组建图(self, mocker):
        mocker.patch(
            "apps.cmdb.services.node_mgmt_sync_service.ModelManage.search_model_info",
            return_value={"attrs": []},
        )
        mocker.patch(
            "apps.cmdb.services.node_mgmt_sync_service.InstanceManage.search_inst",
            return_value=(
                [
                    {"ip_addr": "", "cloud": 1},
                    {"ip_addr": "1.1.1.1", "cloud": ""},
                    {"ip_addr": "2.2.2.2", "cloud_id": 3, "_id": 9},
                ],
                3,
            ),
        )
        out = S._load_existing_host_map(0)
        assert list(out.keys()) == [("2.2.2.2", 3)]
        assert out[("2.2.2.2", 3)]["_id"] == 9

    def test_区域查询跳过空ip(self, mocker):
        mocker.patch.object(
            S,
            "_load_existing_host_map",
            return_value={("10.0.0.1", 1): {"_id": 7, "ip_addr": "10.0.0.1"}},
        )
        nodes = [{"ip": ""}, {"ip_addr": "10.0.0.1"}]
        out = S._query_region_host_instances(1, nodes)
        assert out == [{"_id": 7, "ip_addr": "10.0.0.1"}]


class TestMapHostOsType:
    pytestmark = pytest.mark.unit

    def test_空值返回other(self):
        assert S._map_host_os_type("") == "other"
        assert S._map_host_os_type(None) == "other"

    def test_枚举名与id命中及关键字回退(self, mocker):
        mocker.patch.object(
            S,
            "_host_attr_map",
            return_value={
                "os_type": {"attr_id": "os_type"},
            },
        )
        mocker.patch(
            "apps.cmdb.services.node_mgmt_sync_service.ModelManage.resolve_runtime_enum_options",
            return_value=[
                {"id": "lin", "name": "Ubuntu Linux"},
                {"id": "win", "name": "Windows"},
                "skip",
            ],
        )
        assert S._map_host_os_type("Ubuntu Linux 22") == "lin"
        assert S._map_host_os_type("WIN") == "win"
        mocker.patch(
            "apps.cmdb.services.node_mgmt_sync_service.ModelManage.resolve_runtime_enum_options",
            return_value="bad",
        )
        assert S._map_host_os_type("centos 7") == "1"
        assert S._map_host_os_type("windows server") == "2"
        assert S._map_host_os_type("AIX 7") == "3"
        assert S._map_host_os_type("unixware") == "4"
        assert S._map_host_os_type("solaris-unknown") == "other"

    def test_host_attr_map_attrs非列表返回空(self, mocker):
        mocker.patch(
            "apps.cmdb.services.node_mgmt_sync_service.ModelManage.search_model_info",
            return_value={"attrs": "x"},
        )
        assert S._host_attr_map() == {}


class TestFallbackAndListItems:
    def test_fallback跳过非dict并补默认字段(self):
        task = SimpleNamespace(
            instances=[{"inst_name": "h1", "ip": "1.1.1.1"}, "skip"],
            model_id="host",
            exec_status=CollectRunStatusType.SUCCESS,
        )
        rows = S._fallback_collect_raw_data(task)
        assert len(rows) == 1
        assert rows[0]["model_id"] == "host"
        assert rows[0]["ip_addr"] == "1.1.1.1"
        assert rows[0]["_status"] == "success"

    def test_list_collect_items抽取三桶并跳过非法项(self):
        _collect_task(
            name="nm-items",
            format_data={
                "add": [{"ip_addr": "1.1.1.1"}],
                "update": [{"ip_addr": "2.2.2.2"}, "bad"],
                "delete": [{"ip_addr": "3.3.3.3"}],
            },
            exec_status=CollectRunStatusType.ERROR,
        )
        items = S._list_collect_items()
        ips = {i["ip_addr"] for i in items}
        assert ips == {"1.1.1.1", "2.2.2.2", "3.3.3.3"}
        assert all(i["model_id"] == "host" for i in items)
        assert all(i["_status"] == "error" for i in items)


class TestDisplayPayload:
    def test_collect_task缺raw_data时回填(self):
        task = _collect_task(
            name="nm-fb",
            collect_digest={"all": 2, "add": 2, "message": "ok"},
            instances=[{"inst_name": "h1", "ip": "10.0.0.1"}],
            format_data={},
        )
        out = S._display_payload_from_collect_task(task, S.DISPLAY_SOURCE_COLLECT)
        assert out["display_source"] == S.DISPLAY_SOURCE_COLLECT
        assert out["detail"]["raw_data"]["count"] == 1
        assert out["run"]["status"] == "success"

    def test_build_collect_display合并digest与清空message(self):
        _collect_task(
            name="nm-disp",
            collect_digest={
                "all": 1,
                "add": 1,
                "last_time": "t1",
                "message": "should-clear",
            },
            format_data={"add": [{"ip_addr": "1.1.1.1"}], "__raw_data__": [{"ip_addr": "1.1.1.1"}]},
        )
        out = S._build_collect_display_payload(S.DISPLAY_SOURCE_COLLECT)
        assert out is not None
        assert out["message"]["last_time"] == "t1"
        assert out["message"]["message"] == ""
        assert out["detail"]["raw_data"]["count"] == 1

    def test_build_collect_无任务返回None(self):
        CollectModels.objects.filter(system_code__startswith=S.SYSTEM_TASK_PREFIX).delete()
        assert S._build_collect_display_payload(S.DISPLAY_SOURCE_COLLECT) is None

    def test_get_display_自动采集有数据(self):
        cfg = S.get_task()
        cfg.auto_collect_enabled = True
        cfg.save(update_fields=["auto_collect_enabled"])
        _collect_task(
            name="nm-auto",
            format_data={"add": [{"id": 1}]},
            collect_digest={"all": 1, "add": 1},
        )
        out = S.get_display_payload()
        assert out["display_source"] == S.DISPLAY_SOURCE_COLLECT
        assert out["task"]["id"] == cfg.id

    def test_get_display_自动采集回退最近运行(self):
        CollectModels.objects.filter(system_code__startswith=S.SYSTEM_TASK_PREFIX).delete()
        cfg = S.get_task()
        cfg.auto_collect_enabled = True
        cfg.save(update_fields=["auto_collect_enabled"])
        NodeMgmtSyncRun.objects.create(
            task=cfg,
            run_type=NodeMgmtSyncRun.RUN_TYPE_COLLECT,
            status=NodeMgmtSyncRun.STATUS_SUCCESS,
            summary_json={"all": 3, "add": 3},
            detail_json={"add": {"data": [{"id": 1}]}},
        )
        out = S.get_display_payload()
        assert out["display_source"] == S.DISPLAY_SOURCE_COLLECT
        assert out["message"]["all"] == 3

    def test_get_display_同步最近运行(self):
        CollectModels.objects.filter(system_code__startswith=S.SYSTEM_TASK_PREFIX).delete()
        cfg = S.get_task()
        cfg.auto_collect_enabled = False
        cfg.save(update_fields=["auto_collect_enabled"])
        NodeMgmtSyncRun.objects.create(
            task=cfg,
            run_type=NodeMgmtSyncRun.RUN_TYPE_SYNC,
            status=NodeMgmtSyncRun.STATUS_SUCCESS,
            summary_json={"all": 2},
            detail_json={},
        )
        out = S.get_display_payload()
        assert out["display_source"] == S.DISPLAY_SOURCE_SYNC
        assert out["message"]["all"] == 2

    def test_get_display_无运行空结构(self):
        CollectModels.objects.filter(system_code__startswith=S.SYSTEM_TASK_PREFIX).delete()
        NodeMgmtSyncRun.objects.all().delete()
        cfg = S.get_task()
        cfg.auto_collect_enabled = False
        cfg.save(update_fields=["auto_collect_enabled"])
        out = S.get_display_payload()
        assert out["display_source"] == S.DISPLAY_SOURCE_SYNC
        assert out["run"]["id"] is None


class TestTriggerWrappers:
    def test_trigger委托sync与collect(self, mocker):
        mocker.patch.object(S, "sync_hosts", return_value={"status": "success"})
        mocker.patch.object(S, "collect_hosts", return_value={"status": "ok"})
        assert S.trigger_sync() == {"status": "success"}
        assert S.trigger_collect() == {"status": "ok"}

    def test_execute_collect_task转发exec_task(self, mocker):
        task = SimpleNamespace(id=8, name="t")
        exec_task = mocker.patch(
            "apps.cmdb.services.collect_service.CollectModelService.exec_task",
            return_value={"ok": 1},
        )
        assert S._execute_collect_task(task) == {"ok": 1}
        exec_task.assert_called_once_with(task, "system")
