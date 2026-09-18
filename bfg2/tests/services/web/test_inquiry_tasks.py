import logging
from types import SimpleNamespace

import pytest

from bfg.common.models import Workspace
from bfg.common.services import EmailService
from bfg.web.models import Inquiry, Site
from bfg.web.tasks import _inquiry_notification_recipients, send_inquiry_email


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(
        name="Inquiry notifications",
        slug="inquiry-notifications",
        email="workspace-contact@example.test",
        is_active=True,
    )


@pytest.fixture
def site(workspace):
    return Site.objects.create(
        workspace=workspace,
        name="Public site",
        domain="inquiries.example.test",
        site_title="Public site",
        is_default=True,
    )


@pytest.fixture
def inquiry(workspace, site):
    return Inquiry.objects.create(
        workspace=workspace,
        site=site,
        name="Ada",
        email="ada@example.test",
        subject="A question",
        message="Please contact me",
    )


def _run(inquiry):
    return send_inquiry_email.apply(args=(inquiry.id,), throw=False)


def test_site_recipients_take_priority_over_cluster_admin(settings):
    settings.CLUSTER_ADMIN_EMAIL = "cluster@example.test"
    settings.PLATFORM_ADMIN_EMAIL = "legacy@example.test"

    recipients = _inquiry_notification_recipients({
        "email": {
            "enabled": True,
            "recipients": ["owner@example.test", "OWNER@example.test", "invalid"],
        },
    })

    assert recipients == ["owner@example.test"]


def test_site_recipients_do_not_require_an_enabled_flag(settings):
    settings.CLUSTER_ADMIN_EMAIL = "cluster@example.test"
    settings.PLATFORM_ADMIN_EMAIL = ""

    recipients = _inquiry_notification_recipients({
        "email": {"recipients": ["owner@example.test"]},
    })

    assert recipients == ["owner@example.test"]


def test_explicitly_disabled_site_email_never_falls_back(settings):
    settings.CLUSTER_ADMIN_EMAIL = "cluster@example.test"
    settings.PLATFORM_ADMIN_EMAIL = "legacy@example.test"

    recipients = _inquiry_notification_recipients({
        "email": {"enabled": False, "recipients": ["owner@example.test"]},
    })

    assert recipients == []


def test_cluster_admin_precedes_the_legacy_platform_admin(settings):
    settings.CLUSTER_ADMIN_EMAIL = "cluster@example.test"
    settings.PLATFORM_ADMIN_EMAIL = "legacy@example.test"

    assert _inquiry_notification_recipients({}) == ["cluster@example.test"]


def test_legacy_platform_admin_remains_a_fallback(settings):
    settings.CLUSTER_ADMIN_EMAIL = ""
    settings.PLATFORM_ADMIN_EMAIL = "legacy@example.test"

    assert _inquiry_notification_recipients({}) == ["legacy@example.test"]


@pytest.mark.django_db
def test_task_sends_through_the_workspace_email_config(
    inquiry, settings, monkeypatch
):
    settings.CLUSTER_ADMIN_EMAIL = "cluster@example.test"
    settings.PLATFORM_ADMIN_EMAIL = ""
    email_config = SimpleNamespace(id=73)
    sent = {}

    monkeypatch.setattr(
        EmailService,
        "get_active_config",
        staticmethod(lambda resolved_workspace: email_config),
    )
    monkeypatch.setattr(
        EmailService,
        "send_email",
        staticmethod(lambda **kwargs: sent.update(kwargs)),
    )
    monkeypatch.setattr("bfg.web.tasks.render_to_string", lambda *args, **kwargs: "<p>Inquiry</p>")

    result = _run(inquiry)

    assert result.successful()
    assert sent["workspace"].id == inquiry.workspace_id
    assert sent["to_list"] == ["cluster@example.test"]
    assert sent["config"] is email_config
    assert sent["body_html"] == "<p>Inquiry</p>"
    inquiry.refresh_from_db()
    assert inquiry.notification_sent is True
    assert inquiry.notification_sent_at is not None


@pytest.mark.django_db
def test_task_logs_and_stops_when_workspace_has_no_email_config(
    inquiry, settings, monkeypatch, caplog
):
    settings.CLUSTER_ADMIN_EMAIL = "cluster@example.test"
    settings.PLATFORM_ADMIN_EMAIL = ""
    sent = []
    monkeypatch.setattr(
        EmailService,
        "get_active_config",
        staticmethod(lambda resolved_workspace: None),
    )
    monkeypatch.setattr(
        EmailService,
        "send_email",
        staticmethod(lambda **kwargs: sent.append(kwargs)),
    )

    with caplog.at_level(logging.WARNING, logger="bfg.web.tasks"):
        result = _run(inquiry)

    assert result.successful()
    assert sent == []
    assert "has no active default EmailConfig" in caplog.text
    inquiry.refresh_from_db()
    assert inquiry.notification_sent is False


@pytest.mark.django_db
def test_task_never_uses_workspace_contact_as_an_implicit_recipient(
    inquiry, settings, monkeypatch, caplog
):
    settings.CLUSTER_ADMIN_EMAIL = ""
    settings.PLATFORM_ADMIN_EMAIL = ""
    sent = []
    monkeypatch.setattr(
        EmailService,
        "send_email",
        staticmethod(lambda **kwargs: sent.append(kwargs)),
    )

    with caplog.at_level(logging.WARNING, logger="bfg.web.tasks"):
        result = _run(inquiry)

    assert result.successful()
    assert sent == []
    assert inquiry.workspace.email == "workspace-contact@example.test"
    assert "no Site recipients or deployment-level admin email" in caplog.text


@pytest.mark.django_db
def test_task_does_not_fall_back_when_site_email_is_disabled(
    inquiry, settings, monkeypatch, caplog
):
    inquiry.site.notification_config = {
        "email": {"enabled": False, "recipients": ["owner@example.test"]},
    }
    inquiry.site.save(update_fields=["notification_config"])
    settings.CLUSTER_ADMIN_EMAIL = "cluster@example.test"
    settings.PLATFORM_ADMIN_EMAIL = "legacy@example.test"
    sent = []
    monkeypatch.setattr(
        EmailService,
        "send_email",
        staticmethod(lambda **kwargs: sent.append(kwargs)),
    )

    with caplog.at_level(logging.INFO, logger="bfg.web.tasks"):
        result = _run(inquiry)

    assert result.successful()
    assert sent == []
    assert "Site email notifications are disabled" in caplog.text
