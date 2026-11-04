from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.core.utils.team_utils import get_current_team
from apps.core.utils.user_group import normalize_user_group_ids


@dataclass(frozen=True)
class RequestScope:
    user_id: int
    username: str
    domain: str
    team_id: int
    is_superuser: bool


def request_scope(request, *, refresh_user: bool = False) -> RequestScope:
    request_user = getattr(request, "user", None)
    if request_user is None or not getattr(request_user, "is_authenticated", False):
        raise PermissionDenied("用户未登录")

    user = request_user
    if refresh_user:
        user = get_user_model().objects.filter(pk=request_user.pk).first()
        if user is None or not user.is_active:
            raise PermissionDenied("用户身份已失效")

    raw_team = get_current_team(request)
    try:
        team_id = int(raw_team)
    except (TypeError, ValueError) as error:
        raise ValidationError({"current_team": "缺少或非法的 current_team"}) from error
    if team_id <= 0:
        raise ValidationError({"current_team": "缺少或非法的 current_team"})

    is_superuser = bool(getattr(user, "is_superuser", False))
    if not is_superuser and team_id not in set(normalize_user_group_ids(getattr(user, "group_list", None))):
        raise PermissionDenied("无权访问当前组织")

    return RequestScope(
        user_id=int(user.pk),
        username=str(user.username),
        domain=str(getattr(user, "domain", "domain.com")),
        team_id=team_id,
        is_superuser=is_superuser,
    )
