"""Kubernetes 工具通用函数单元测试 (kubernetes/utils)。

覆盖字节/资源量解析、线程局部集群名、kubeconfig 预处理 (文件引用 -> inline data)、
YAML 字符串表示策略。文件系统/yaml 之外不触真实集群。
"""

import base64

import pytest
import yaml

from apps.opspilot.metis.llm.tools.kubernetes import utils as k8s


class TestFormatBytes:
    def test_bytes(self):
        assert k8s.format_bytes(512) == "512 B"

    def test_kib(self):
        assert k8s.format_bytes(2048) == "2.0 KiB"

    def test_mib(self):
        assert k8s.format_bytes(5 * 1024 * 1024) == "5.0 MiB"

    def test_gib_rounding(self):
        assert k8s.format_bytes(int(2.5 * 1024 ** 3)) == "2.5 GiB"


class TestParseResourceQuantity:
    def test_empty_returns_zero(self):
        assert k8s.parse_resource_quantity("") == 0
        assert k8s.parse_resource_quantity(None) == 0

    def test_cpu_millicores(self):
        assert k8s.parse_resource_quantity("100m") == 0.1

    def test_memory_gi(self):
        assert k8s.parse_resource_quantity("1Gi") == 1024 ** 3

    def test_memory_mi(self):
        assert k8s.parse_resource_quantity("500Mi") == 500 * 1024 ** 2

    def test_decimal_si_k(self):
        assert k8s.parse_resource_quantity("2K") == 2000

    def test_plain_number(self):
        assert k8s.parse_resource_quantity("4") == 4.0

    def test_invalid_returns_zero(self):
        assert k8s.parse_resource_quantity("notanumber") == 0


class TestClusterNameThreadLocal:
    def test_set_and_get(self):
        k8s._set_current_cluster_name("prod-cluster")
        assert k8s.get_current_cluster_name() == "prod-cluster"

    def test_reset_to_empty(self):
        k8s._set_current_cluster_name("")
        assert k8s.get_current_cluster_name() == ""


class TestResolveFileToInlineData:
    def test_no_op_when_key_absent(self):
        obj = {"other": 1}
        k8s._resolve_file_to_inline_data(obj, "certificate-authority", "certificate-authority-data")
        assert obj == {"other": 1}

    def test_existing_inline_data_drops_file_ref(self):
        obj = {"certificate-authority": "/path", "certificate-authority-data": "ABC"}
        k8s._resolve_file_to_inline_data(obj, "certificate-authority", "certificate-authority-data")
        assert "certificate-authority" not in obj
        assert obj["certificate-authority-data"] == "ABC"

    def test_missing_file_raises(self):
        obj = {"certificate-authority": "/definitely/not/here.crt"}
        with pytest.raises(ValueError, match="引用的文件不存在"):
            k8s._resolve_file_to_inline_data(obj, "certificate-authority", "certificate-authority-data")

    def test_base64_encode_file(self, tmp_path):
        f = tmp_path / "ca.crt"
        f.write_bytes(b"CERTDATA")
        obj = {"certificate-authority": str(f)}
        k8s._resolve_file_to_inline_data(obj, "certificate-authority", "certificate-authority-data", base64_encode=True)
        assert obj["certificate-authority-data"] == base64.standard_b64encode(b"CERTDATA").decode()
        assert "certificate-authority" not in obj

    def test_plain_text_token_file(self, tmp_path):
        f = tmp_path / "token"
        f.write_text("my-token\n")
        obj = {"tokenFile": str(f)}
        k8s._resolve_file_to_inline_data(obj, "tokenFile", "token", base64_encode=False)
        assert obj["token"] == "my-token"
        assert "tokenFile" not in obj


class TestPreprocessKubeconfig:
    def test_invalid_yaml_returned_asis(self):
        bad = "::not: valid: yaml: ["
        assert k8s._preprocess_kubeconfig(bad) == bad

    def test_non_dict_returned_asis(self):
        assert k8s._preprocess_kubeconfig("- a\n- b\n") == "- a\n- b\n"

    def test_token_stripped(self):
        cfg = {"users": [{"user": {"token": "  abc\n"}}]}
        out = k8s._preprocess_kubeconfig(yaml.safe_dump(cfg))
        parsed = yaml.safe_load(out)
        assert parsed["users"][0]["user"]["token"] == "abc"

    def test_ca_file_inlined(self, tmp_path):
        ca = tmp_path / "ca.crt"
        ca.write_bytes(b"CA")
        cfg = {"clusters": [{"cluster": {"certificate-authority": str(ca)}}]}
        out = k8s._preprocess_kubeconfig(yaml.safe_dump(cfg))
        parsed = yaml.safe_load(out)
        cluster = parsed["clusters"][0]["cluster"]
        assert "certificate-authority" not in cluster
        assert cluster["certificate-authority-data"] == base64.standard_b64encode(b"CA").decode()

    def test_empty_user_skipped_and_client_certs_inlined(self, tmp_path):
        cert = tmp_path / "c.crt"
        cert.write_bytes(b"CERT")
        key = tmp_path / "c.key"
        key.write_bytes(b"KEY")
        token = tmp_path / "tok"
        token.write_text("secret-token\n")
        cfg = {
            "users": [
                {"user": {}},
                {
                    "user": {
                        "client-certificate": str(cert),
                        "client-key": str(key),
                        "tokenFile": str(token),
                    }
                },
            ]
        }
        parsed = yaml.safe_load(k8s._preprocess_kubeconfig(yaml.safe_dump(cfg)))
        empty, filled = parsed["users"]
        assert empty["user"] == {}
        user = filled["user"]
        assert "client-certificate" not in user
        assert "client-key" not in user
        assert "tokenFile" not in user
        assert user["client-certificate-data"] == base64.standard_b64encode(b"CERT").decode()
        assert user["client-key-data"] == base64.standard_b64encode(b"KEY").decode()
        assert user["token"] == "secret-token"

    def test_resolve_file_read_error_keeps_path(self, tmp_path, monkeypatch):
        target = tmp_path / "ca.crt"
        target.write_bytes(b"CA")
        obj = {"certificate-authority": str(target)}
        real_open = open

        def _open(path, *a, **k):
            if str(path) == str(target):
                raise OSError("perm")
            return real_open(path, *a, **k)

        monkeypatch.setattr("builtins.open", _open)
        k8s._resolve_file_to_inline_data(obj, "certificate-authority", "certificate-authority-data")
        assert obj == {"certificate-authority": str(target)}


class TestValidateKubeconfigApiServers:
    def test_empty_invalid_yaml_and_non_dict_are_noop(self):
        k8s.validate_kubeconfig_api_servers("")
        k8s.validate_kubeconfig_api_servers("   ")
        k8s.validate_kubeconfig_api_servers(":[")
        k8s.validate_kubeconfig_api_servers("- a\n- b\n")

    def test_validates_server_urls(self, monkeypatch):
        seen = []
        monkeypatch.setattr(k8s.SSRFValidator, "validate", lambda url: seen.append(url) or url)
        k8s.validate_kubeconfig_api_servers(
            yaml.safe_dump(
                {
                    "clusters": [
                        "skip",
                        {"cluster": {"server": " https://k8s.example.com "}},
                        {"cluster": {}},
                    ]
                }
            )
        )
        assert seen == ["https://k8s.example.com"]


class TestPrepareContext:
    def test_legacy_kubeconfig_data_loads_client(self, monkeypatch):
        loaded = []
        monkeypatch.setattr(
            k8s.config,
            "load_kube_config",
            lambda config_file=None: loaded.append(config_file.read()),
        )
        monkeypatch.setattr(k8s.SSRFValidator, "validate", lambda url: url)
        monkeypatch.setattr(
            k8s.config,
            "list_kube_config_contexts",
            lambda: ([], {"name": "ctx", "context": {"cluster": "prod"}}),
        )
        cfg = yaml.safe_dump({"clusters": [{"cluster": {"server": "https://k8s.example.com"}}]})
        k8s.prepare_context({"configurable": {"kubeconfig_data": cfg.replace("\n", "\\n")}})
        assert "https://k8s.example.com" in loaded[0]
        assert k8s.get_current_cluster_name() == "prod"

    def test_default_then_incluster_fallback(self, monkeypatch):
        monkeypatch.setattr(k8s.config, "load_kube_config", lambda: (_ for _ in ()).throw(RuntimeError("no file")))
        called = []
        monkeypatch.setattr(k8s.config, "load_incluster_config", lambda: called.append("incluster"))
        monkeypatch.setattr(k8s, "get_current_cluster_name", lambda: "already")
        k8s.prepare_context({"configurable": {}})
        assert called == ["incluster"]

    def test_load_failure_wraps_message(self, monkeypatch):
        monkeypatch.setattr(k8s.config, "load_kube_config", lambda: (_ for _ in ()).throw(RuntimeError("no file")))
        monkeypatch.setattr(k8s.config, "load_incluster_config", lambda: (_ for _ in ()).throw(RuntimeError("no sa")))
        with pytest.raises(Exception, match="无法加载 Kubernetes 配置"):
            k8s.prepare_context({"configurable": {}})


class TestRepresentStrNoFold:
    def test_long_string_quoted(self):
        long_val = "x" * 100
        cfg = {"users": [{"user": {"token": long_val}}]}
        out = k8s._preprocess_kubeconfig(yaml.safe_dump(cfg))
        # 长 token 应被双引号包裹,且 yaml 可往返解析
        assert yaml.safe_load(out)["users"][0]["user"]["token"] == long_val
