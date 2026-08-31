"""SkillPackageViewSet.get_queryset：按启用状态与关键字过滤。"""
import uuid

import pytest
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.opspilot.models import SkillPackage
from apps.opspilot.viewsets.llm_view import SkillPackageViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()


def _view(django_request):
    view = SkillPackageViewSet()
    view.request = Request(django_request)
    view.format_kwarg = None
    view.action = "list"
    return view


def test_skill_package_queryset_filters_enabled_and_search():
    user = UserFactory(username=f"pkg-{uuid.uuid4().hex[:8]}", domain="domain.com", is_superuser=True, roles=[], group_list=[{"id": 1, "name": "T1"}])
    enabled = SkillPackage.objects.create(package_id="k8s-specialist", name="K8s 专家", description="集群诊断", category="ops", team=[1], is_enabled=True)
    SkillPackage.objects.create(package_id="disabled-pack", name="关闭包", description="x", category="ops", team=[1], is_enabled=False)
    SkillPackage.objects.create(package_id="other", name="其他", description="无关", category="chat", team=[1], is_enabled=True)

    req = factory.get("/skill-packages/?is_enabled=true&search=K8s")
    force_authenticate(req, user=user)
    req.COOKIES["current_team"] = "1"
    ids = list(_view(req).get_queryset().values_list("id", flat=True))
    assert ids == [enabled.id]

    req2 = factory.get("/skill-packages/?is_enabled=0&search=disabled")
    force_authenticate(req2, user=user)
    req2.COOKIES["current_team"] = "1"
    disabled_ids = list(_view(req2).get_queryset().values_list("package_id", flat=True))
    assert disabled_ids == ["disabled-pack"]
