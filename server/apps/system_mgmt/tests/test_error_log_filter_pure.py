"""ErrorLogFilter.app 多选：空值原样返回，逗号分隔走 app__in。"""
from unittest.mock import MagicMock

import pytest

from apps.system_mgmt.viewset.error_log_viewset import ErrorLogFilter

pytestmark = pytest.mark.unit


def test_filter_app_in_empty_returns_queryset():
    qs = MagicMock(name="qs")
    filt = ErrorLogFilter()
    assert filt.filter_app_in(qs, "app", "") is qs
    assert filt.filter_app_in(qs, "app", "  ,  ") is qs
    qs.filter.assert_not_called()


def test_filter_app_in_splits_and_strips_apps():
    qs = MagicMock()
    filtered = MagicMock(name="filtered")
    qs.filter.return_value = filtered
    result = ErrorLogFilter().filter_app_in(qs, "app", "system_mgmt, opspilot ,")
    qs.filter.assert_called_once_with(app__in=["system_mgmt", "opspilot"])
    assert result is filtered
