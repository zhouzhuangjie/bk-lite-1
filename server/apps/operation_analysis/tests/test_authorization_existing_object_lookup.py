"""导入鉴权：按对象类型查找已存在记录与批量 lookup。"""
from types import SimpleNamespace

import pytest

from apps.operation_analysis.constants.import_export import ImportExportErrorCode, ObjectType
from apps.operation_analysis.models.datasource_models import DataSourceAPIModel, NameSpace
from apps.operation_analysis.models.models import Architecture, Dashboard, Report, Screen, Topology
from apps.operation_analysis.services.import_export.authorization_service import ImportExportAuthorizationService

AUTH = ImportExportAuthorizationService
pytestmark = pytest.mark.django_db


def test_get_existing_object_and_batch_lookup_by_type():
    dash = Dashboard.objects.create(name="auth-dash", groups=[1])
    topo = Topology.objects.create(name="auth-topo", groups=[1])
    arch = Architecture.objects.create(name="auth-arch", groups=[1])
    screen = Screen.objects.create(name="auth-screen", groups=[1])
    report = Report.objects.create(name="auth-report", groups=[1])
    ns = NameSpace.objects.create(name="auth-ns", account="a", password="p", domain="d")
    ds = DataSourceAPIModel.objects.create(name="auth-ds", rest_api="http://127.0.0.1/api", groups=[1])

    assert AUTH.get_existing_object(ObjectType.DASHBOARD, SimpleNamespace(name="auth-dash")).id == dash.id
    assert AUTH.get_existing_object(ObjectType.TOPOLOGY, SimpleNamespace(name="auth-topo")).id == topo.id
    assert AUTH.get_existing_object(ObjectType.ARCHITECTURE, SimpleNamespace(name="auth-arch")).id == arch.id
    assert AUTH.get_existing_object(ObjectType.SCREEN, SimpleNamespace(name="auth-screen")).id == screen.id
    assert AUTH.get_existing_object(ObjectType.REPORT, SimpleNamespace(name="auth-report")).id == report.id
    assert AUTH.get_existing_object(ObjectType.NAMESPACE, SimpleNamespace(name="auth-ns")).id == ns.id
    assert (
        AUTH.get_existing_object(
            ObjectType.DATASOURCE, SimpleNamespace(name="auth-ds", rest_api="http://127.0.0.1/api")
        ).id
        == ds.id
    )
    assert AUTH.get_existing_object(ObjectType.DASHBOARD, SimpleNamespace(name="missing")) is None

    batch = AUTH.get_existing_objects_batch(
        ObjectType.DASHBOARD,
        [SimpleNamespace(name="auth-dash"), SimpleNamespace(name="missing")],
    )
    assert set(batch) == {"auth-dash"}
    assert batch["auth-dash"].id == dash.id
    assert AUTH.get_existing_objects_batch(ObjectType.DASHBOARD, []) == {}
    ds_batch = AUTH.get_existing_objects_batch(
        ObjectType.DATASOURCE,
        [SimpleNamespace(name="auth-ds", rest_api="http://127.0.0.1/api")],
    )
    assert ds_batch[("auth-ds", "http://127.0.0.1/api")].id == ds.id
    assert AUTH._item_lookup_key(ObjectType.DATASOURCE, SimpleNamespace(name="a", rest_api="b")) == ("a", "b")
    assert AUTH._item_lookup_key(ObjectType.DASHBOARD, SimpleNamespace(name="a")) == "a"
    err = AUTH.build_permission_error(
        ObjectType.DASHBOARD, SimpleNamespace(key="dash::a"), ["view-View"], "denied"
    )
    assert err == {
        "code": ImportExportErrorCode.IMPORT_PERMISSION_DENIED,
        "message": "denied",
        "object_key": "dash::a",
        "object_type": "dashboard",
        "required_permission": "view-View",
        "details": {"required_permissions": ["view-View"]},
    }
