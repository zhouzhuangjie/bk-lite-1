from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.itsm.management.commands.itsm_dispatch import MAX_BATCH_SIZE


@pytest.mark.django_db
def test_dispatch_command_once_processes_bounded_batch():
    client = MagicMock()
    with (
        patch("apps.itsm.management.commands.itsm_dispatch.FlowableClient", return_value=client),
        patch("apps.itsm.management.commands.itsm_dispatch.due_command_ids", return_value=["command-1"]) as due,
        patch("apps.itsm.management.commands.itsm_dispatch.dispatch_command") as dispatch,
    ):
        call_command("itsm_dispatch", once=True, batch_size=5)

    due.assert_called_once_with(batch_size=5)
    dispatch.assert_called_once_with("command-1", client=client)
    client.close.assert_called_once_with()


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"once": True, "interval": 0.1}, "--interval"),
        ({"once": True, "batch_size": MAX_BATCH_SIZE + 1}, "--batch-size"),
    ],
)
def test_dispatch_command_rejects_unbounded_options(arguments, message):
    with pytest.raises(CommandError, match=message):
        call_command("itsm_dispatch", **arguments)
