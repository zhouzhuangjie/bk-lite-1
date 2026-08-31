"""SSRFValidator 剩余：白名单解析失败、DNS 空结果、非法 IP、主机白名单。"""
import ipaddress
import socket
from unittest.mock import patch

import pytest

from apps.core.utils.ssrf_validator import SSRFError, SSRFValidator

pytestmark = pytest.mark.unit


def test_get_allowed_networks_skips_bad_cidr_and_fail_closed():
    with patch(
        "apps.system_mgmt.utils.network_whitelist_cache.get_network_whitelist_cidrs",
        return_value=["10.0.0.0/8", "not-a-cidr"],
    ):
        nets = SSRFValidator._get_allowed_networks()
    assert nets == [ipaddress.ip_network("10.0.0.0/8")]

    with patch(
        "apps.system_mgmt.utils.network_whitelist_cache.get_network_whitelist_cidrs",
        side_effect=RuntimeError("cache down"),
    ):
        assert SSRFValidator._get_allowed_networks() == []


def test_is_blocked_ip_allows_public_ipv6_and_skips_v4_networks():
    ipv6 = ipaddress.ip_address("2606:4700:4700::1111")
    blocked, reason = SSRFValidator._is_blocked_ip(ipv6)
    assert blocked is False
    assert reason == ""


def test_validate_allowlist_and_dns_failures():
    with pytest.raises(SSRFError, match="不在允许列表"):
        SSRFValidator.validate("https://evil.example.com/", allowlist={"good.example.com"})

    with patch("socket.getaddrinfo", side_effect=socket.gaierror(8, "nxdomain")):
        with pytest.raises(SSRFError, match="无法解析主机名"):
            SSRFValidator.validate("https://missing.example.com/")

    with patch("socket.getaddrinfo", return_value=[]):
        with pytest.raises(SSRFError, match="无法解析"):
            SSRFValidator.validate("https://empty.example.com/")

    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("not-an-ip", 80))]):
        assert SSRFValidator.validate("https://ok.example.com/") == "https://ok.example.com/"


def test_validate_llm_and_callback_dns_empty_and_invalid_ip():
    with patch("socket.getaddrinfo", side_effect=socket.gaierror(8, "nxdomain")):
        with pytest.raises(SSRFError, match="无法解析主机名"):
            SSRFValidator.validate_llm_endpoint("http://llm.internal/")
        with pytest.raises(SSRFError, match="无法解析主机名"):
            SSRFValidator.validate_callback("http://cb.internal/hook")

    with patch("socket.getaddrinfo", return_value=[]):
        with pytest.raises(SSRFError, match="无法解析"):
            SSRFValidator.validate_llm_endpoint("http://llm.internal/")
        with pytest.raises(SSRFError, match="无法解析"):
            SSRFValidator.validate_callback("http://cb.internal/hook")

    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("bad-ip", 80))]):
        assert SSRFValidator.validate_llm_endpoint("http://llm.internal/") == "http://llm.internal/"
        assert SSRFValidator.validate_callback("http://cb.internal/hook") == "http://cb.internal/hook"
