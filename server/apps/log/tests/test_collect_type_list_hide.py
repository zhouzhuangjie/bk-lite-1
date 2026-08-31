"""CollectTypeViewSet.list：隐藏 Packetbeat/http，并回填 display_name。"""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.log.models import CollectType
from apps.log.views.collect_config import CollectTypeViewSet, should_hide_collect_type_entry

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()


def test_should_hide_packetbeat_http_only():
    assert should_hide_collect_type_entry({"collector": "Packetbeat", "name": "http"}) is True
    assert should_hide_collect_type_entry({"collector": "Packetbeat", "name": "flows"}) is False
    assert should_hide_collect_type_entry({"collector": "Filebeat", "name": "http"}) is False


def test_list_hides_packetbeat_http_and_sets_display_name():
    CollectType.objects.create(name="http", collector="Packetbeat", icon="i", description="hidden")
    CollectType.objects.create(name="logfile", collector="Filebeat", icon="i", description="file logs")
    user = UserFactory(is_superuser=True)
    req = factory.get("/")
    force_authenticate(req, user=user)
    req.COOKIES["current_team"] = "1"
    lan = SimpleNamespace(get=lambda key: "日志文件" if key.endswith(".name") else "desc")
    with patch("apps.log.views.collect_config.LanguageLoader", return_value=lan):
        resp = CollectTypeViewSet.as_view({"get": "list"})(req)
    payload = resp.content.decode("utf-8")
    data = json.loads(payload)["data"]
    names = {row["name"] for row in data}
    assert "http" not in names
    assert "logfile" in names
    logfile = next(row for row in data if row["name"] == "logfile")
    assert logfile["display_name"] == "日志文件"
    assert logfile["display_description"] == "desc"
