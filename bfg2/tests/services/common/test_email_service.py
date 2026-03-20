from types import SimpleNamespace

import pytest

from bfg.common.services.email_service import EmailService


def test_send_email_raises_without_active_config(monkeypatch):
    workspace = SimpleNamespace(id=7)
    monkeypatch.setattr(EmailService, "get_active_config", staticmethod(lambda _workspace: None))
    with pytest.raises(ValueError, match="No active email config"):
        EmailService.send_email(workspace, ["u@example.com"], "s", "body", config=None)
