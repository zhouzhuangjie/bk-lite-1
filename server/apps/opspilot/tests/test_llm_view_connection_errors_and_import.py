"""llm_view 剩余错误契约：连接 ValueError/Exception、模型名校验、技能包导入失败。

对照契约：各 test_*_connection 把 ValueError 原样回 400；通用 Exception 带驱动名前缀；
Redis 额外翻译 RedisError/TypeError。LLMModel 名称校验空值/类型/异常一律空串。
import_zip 无文件/非 zip/ValueError→400，其它异常→500。
"""
import json
import uuid
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from redis.exceptions import RedisError
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.opspilot.models import LLMModel, ModelVendor
from apps.opspilot.viewsets.llm_view import LLMModelViewSet, ObjFilter, SkillPackageViewSet, SkillToolsViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()
MOD = "apps.opspilot.viewsets.llm_view"


def _su(name="llm-err"):
    return UserFactory(
        username=f"{name}-{uuid.uuid4().hex[:8]}",
        domain="domain.com",
        roles=[],
        is_superuser=True,
        group_list=[{"id": 1, "name": "T1"}],
    )


def _body(resp):
    if hasattr(resp, "data") and isinstance(resp.data, dict) and "result" in resp.data:
        return resp.data
    return json.loads(resp.content.decode("utf-8"))


def _dispatch(viewset, action, method, data=None, pk=None, user=None):
    path = "/"
    if method in ("post", "put", "patch"):
        request = getattr(factory, method)(path, data=data or {}, format="json")
    elif method == "delete":
        request = factory.delete(path)
    else:
        request = factory.get(path)
    force_authenticate(request, user=user or _su())
    request.COOKIES["current_team"] = "1"
    view = viewset.as_view({method: action})
    return view(request, pk=pk) if pk is not None else view(request)


class TestConnectionValueErrorAndException:
    def test_redis_valueerror_and_rediserror_and_typeerror(self, mocker):
        mocker.patch(f"{MOD}.SSRFValidator.validate", return_value=None)
        mocker.patch(f"{MOD}.normalize_redis_instance", side_effect=ValueError("host required"))
        resp = _dispatch(SkillToolsViewSet, "test_redis_connection", "post", {"host": "redis.example.com"})
        assert resp.status_code == 400
        assert _body(resp) == {"result": False, "message": "host required"}

        mocker.patch(f"{MOD}.normalize_redis_instance", return_value="inst")
        mocker.patch(f"{MOD}.test_redis_instance", side_effect=RedisError("timeout"))
        resp = _dispatch(SkillToolsViewSet, "test_redis_connection", "post", {"host": "redis.example.com"})
        assert resp.status_code == 400
        assert _body(resp)["result"] is False
        assert _body(resp)["message"] == "Redis connection test failed: timeout"

        mocker.patch(f"{MOD}.test_redis_instance", side_effect=TypeError("bad port"))
        resp = _dispatch(SkillToolsViewSet, "test_redis_connection", "post", {"url": "https://redis.example.com"})
        assert resp.status_code == 400
        assert _body(resp)["message"] == "Redis connection test failed: bad port"

    def test_mysql_valueerror_keeps_raw_message(self, mocker):
        mocker.patch(f"{MOD}.SSRFValidator.validate", return_value=None)
        mocker.patch(f"{MOD}.normalize_mysql_instance", side_effect=ValueError("port invalid"))
        resp = _dispatch(SkillToolsViewSet, "test_mysql_connection", "post", {"host": "db.example.com"})
        assert resp.status_code == 400
        assert _body(resp) == {"result": False, "message": "port invalid"}

    def test_oracle_valueerror_and_exception(self, mocker):
        mocker.patch(f"{MOD}.SSRFValidator.validate", return_value=None)
        mocker.patch(f"{MOD}.normalize_oracle_instance", side_effect=ValueError("sid required"))
        resp = _dispatch(SkillToolsViewSet, "test_oracle_connection", "post", {"host": "ora.example.com"})
        assert resp.status_code == 400
        assert _body(resp)["message"] == "sid required"

        mocker.patch(f"{MOD}.normalize_oracle_instance", return_value="inst")
        mocker.patch(f"{MOD}.test_oracle_instance", side_effect=RuntimeError("listener down"))
        resp = _dispatch(SkillToolsViewSet, "test_oracle_connection", "post", {"host": "ora.example.com"})
        assert resp.status_code == 400
        assert _body(resp)["message"] == "Oracle connection test failed: listener down"

    def test_mssql_postgres_es_jenkins_k8s_valueerror_and_exception(self, mocker):
        mocker.patch(f"{MOD}.SSRFValidator.validate", return_value=None)
        cases = [
            (
                "test_mssql_connection",
                "apps.opspilot.metis.llm.tools.mssql.connection.normalize_mssql_instance",
                "apps.opspilot.metis.llm.tools.mssql.connection.test_mssql_instance",
                {"host": "mssql.example.com"},
                "MSSQL",
            ),
            (
                "test_postgres_connection",
                f"{MOD}.normalize_postgres_instance",
                f"{MOD}.test_postgres_instance",
                {"host": "pg.example.com"},
                "PostgreSQL",
            ),
            (
                "test_es_connection",
                f"{MOD}.normalize_es_instance",
                f"{MOD}.test_es_instance",
                {"url": "https://es.example.com"},
                "Elasticsearch",
            ),
            (
                "test_jenkins_connection",
                f"{MOD}.normalize_jenkins_instance",
                f"{MOD}.test_jenkins_instance",
                {"jenkins_url": "https://ci.example.com"},
                "Jenkins",
            ),
            (
                "test_kubernetes_connection",
                f"{MOD}.normalize_kubernetes_instance",
                f"{MOD}.test_kubernetes_instance",
                {"kubeconfig_data": "apiVersion: v1\nclusters: []\n"},
                "Kubernetes",
            ),
        ]
        for action, norm_path, test_path, data, label in cases:
            mocker.patch(norm_path, side_effect=ValueError(f"{label} host missing"))
            resp = _dispatch(SkillToolsViewSet, action, "post", data)
            assert resp.status_code == 400, action
            assert _body(resp) == {"result": False, "message": f"{label} host missing"}

            mocker.patch(norm_path, return_value="inst")
            mocker.patch(test_path, side_effect=RuntimeError("probe boom"))
            resp = _dispatch(SkillToolsViewSet, action, "post", data)
            assert resp.status_code == 400, action
            assert _body(resp)["result"] is False
            assert _body(resp)["message"] == f"{label} connection test failed: probe boom"


class TestGuardAndSsrfResponse:
    def test_guard_connection_url_skips_empty(self, mocker):
        validate = mocker.patch(f"{MOD}.SSRFValidator.validate")
        SkillToolsViewSet._guard_connection_url("")
        SkillToolsViewSet._guard_connection_url("   ")
        SkillToolsViewSet._guard_connection_url(None)
        validate.assert_not_called()

    def test_ssrf_error_response_uses_loader_message(self):
        view = SkillToolsViewSet()
        view.loader = type("L", (), {"get": staticmethod(lambda key: "目标禁止")})()
        resp = view._ssrf_error_response("private host")
        assert resp.status_code == 400
        assert _body(resp) == {"result": False, "message": "目标禁止: private host"}

    def test_obj_filter_enabled_passthrough_and_true_false(self):
        class Dummy:
            def __init__(self):
                self.kwargs = None

            def filter(self, **kwargs):
                self.kwargs = kwargs
                return "filtered"

        dummy = Dummy()
        assert ObjFilter.filter_enabled(dummy, "enabled", "") is dummy
        assert ObjFilter.filter_enabled(dummy, "enabled", "1") == "filtered"
        assert dummy.kwargs == {"enabled": True}
        assert ObjFilter.filter_enabled(dummy, "enabled", "0") == "filtered"
        assert dummy.kwargs == {"enabled": False}


class TestLLMModelNameValidation:
    def test_empty_or_invalid_inputs_return_empty_string(self):
        vs = LLMModelViewSet()
        assert vs._validate_llm_model_name("", [{"id": 1, "name": "T1"}], [1], 9) == ""
        assert vs._validate_llm_model_name(None, [{"id": 1, "name": "T1"}], [1], 9) == ""
        assert vs._validate_llm_model_name(12, [{"id": 1, "name": "T1"}], [1], 9) == ""
        assert vs._validate_llm_model_name("m", "not-list", [1], 9) == ""
        assert vs._validate_llm_model_name("m", [{"id": 1, "name": "T1"}], "not-list", 9) == ""
        assert vs._validate_llm_model_name("m", [{"id": 1, "name": "T1"}], [1], None) == ""
        assert vs._validate_llm_model_name("m", [{"id": 1, "name": "T1"}], [1], 0) == ""

    def test_conflict_falls_back_to_team_id_label(self):
        vendor = ModelVendor.objects.create(name="v-name", api_base="https://api.example.com", api_key="k")
        LLMModel.objects.create(name="dup-name", team=[7], vendor=vendor, model="a")
        vs = LLMModelViewSet()
        msg = vs._validate_llm_model_name("dup-name", [{"id": 1, "name": "T1"}], [7], vendor.id)
        assert msg == "Team-7"

    def test_exclude_id_skips_self_and_exception_swallows(self):
        vendor = ModelVendor.objects.create(name="v-ex", api_base="https://api.example.com", api_key="k")
        mine = LLMModel.objects.create(name="only-me", team=[1], vendor=vendor, model="a")
        vs = LLMModelViewSet()
        assert vs._validate_llm_model_name("only-me", [{"id": 1, "name": "T1"}], [1], vendor.id, exclude_id=mine.id) == ""

        vs.queryset = None
        assert vs._validate_llm_model_name("only-me", [{"id": 1, "name": "T1"}], [1], vendor.id) == ""

    def test_create_with_loader_formats_conflict_message(self, mocker):
        from types import SimpleNamespace

        vendor = ModelVendor.objects.create(name="v-load", api_base="https://api.example.com", api_key="k")
        LLMModel.objects.create(name="taken", team=[1], vendor=vendor, model="a")
        mocker.patch.object(LLMModelViewSet, "_validate_org_field_permission")
        user = _su("llm-load")
        req = SimpleNamespace(
            data={"name": "taken", "team": [1], "vendor": vendor.id, "model": "b"},
            user=user,
            COOKIES={"current_team": "1"},
        )
        view = LLMModelViewSet()
        view.loader = type("L", (), {"get": staticmethod(lambda key: "组内已存在: {validate_msg}")})()
        view.queryset = LLMModel.objects.all()
        resp = LLMModelViewSet.create.__wrapped__(view, req)
        assert _body(resp) == {"result": False, "message": "组内已存在: T1"}


class TestImportZipErrors:
    def test_missing_file_locks_message(self):
        req = factory.post("/", data={}, format="multipart")
        force_authenticate(req, user=_su())
        req.COOKIES["current_team"] = "1"
        resp = SkillPackageViewSet.as_view({"post": "import_zip"})(req)
        assert resp.status_code == 400
        assert _body(resp) == {"result": False, "message": "请上传技能包 ZIP 文件"}

    def test_non_zip_locks_message(self):
        upload = SimpleUploadedFile("pkg.txt", b"data", content_type="text/plain")
        req = factory.post("/", data={"file": upload}, format="multipart")
        force_authenticate(req, user=_su())
        req.COOKIES["current_team"] = "1"
        resp = SkillPackageViewSet.as_view({"post": "import_zip"})(req)
        assert resp.status_code == 400
        assert _body(resp) == {"result": False, "message": "技能包必须是 ZIP 文件"}

    def test_importer_valueerror_returns_400(self, mocker):
        mocker.patch(f"{MOD}.SkillPackageImporter.import_zip", side_effect=ValueError("缺少 SKILL.md"))
        upload = SimpleUploadedFile("pkg.zip", b"PK\x03\x04fake", content_type="application/zip")
        req = factory.post("/", data={"file": upload}, format="multipart")
        force_authenticate(req, user=_su())
        req.COOKIES["current_team"] = "1"
        resp = SkillPackageViewSet.as_view({"post": "import_zip"})(req)
        assert resp.status_code == 400
        assert _body(resp) == {"result": False, "message": "缺少 SKILL.md"}

    def test_importer_exception_returns_500(self, mocker):
        mocker.patch(f"{MOD}.SkillPackageImporter.import_zip", side_effect=RuntimeError("disk full"))
        upload = SimpleUploadedFile("pkg.zip", b"PK\x03\x04fake", content_type="application/zip")
        req = factory.post("/", data={"file": upload}, format="multipart")
        force_authenticate(req, user=_su())
        req.COOKIES["current_team"] = "1"
        resp = SkillPackageViewSet.as_view({"post": "import_zip"})(req)
        assert resp.status_code == 500
        assert _body(resp) == {"result": False, "message": "disk full"}
