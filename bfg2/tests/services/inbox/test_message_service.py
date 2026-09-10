import pytest

from bfg.inbox.services.message_service import MessageService


def test_render_template_replaces_context():
    service = MessageService(workspace=None, user=None)
    rendered = service._render_template("Hello {{ name }}", {"name": "BFG"})
    assert rendered == "Hello BFG"


# ---------------------------------------------------------------------------
# send_from_template channel selection (regression coverage)
# ---------------------------------------------------------------------------
@pytest.fixture
def workspace(db):
    from bfg.common.models import Workspace

    return Workspace.objects.create(name="ACME", slug="acme-msgsvc")


def _customer(workspace, username, *, email="", email_pref=True):
    from bfg.common.models import Customer, User
    from bfg.common.models.preferences import UserPreferences

    user = User.objects.create(username=username, email=email)
    UserPreferences.objects.create(user=user, email_notifications=email_pref)
    return Customer.all_objects.create(workspace=workspace, user=user, customer_number=username)


def _template(workspace, code, **overrides):
    from bfg.inbox.models import MessageTemplate

    fields = dict(
        workspace=workspace, name=code, code=code, event=code, language="en", is_active=True,
        app_message_enabled=False, email_enabled=False, sms_enabled=False, push_enabled=False,
        app_message_title="Hi {{ name }}", app_message_body="Body {{ name }}",
        email_subject="Subject {{ name }}", email_body="Email {{ name }}",
    )
    fields.update(overrides)
    return MessageTemplate.objects.create(**fields)


@pytest.mark.django_db
def test_email_only_template_does_not_require_app_message(workspace, monkeypatch):
    """Regression: it used to raise ValidationError when app_message_enabled was False."""
    sent = []
    monkeypatch.setattr(MessageService, "_send_email",
                        lambda self, recipient, *a, **k: sent.append(recipient.id))
    customer = _customer(workspace, "alice", email="alice@example.com", email_pref=True)
    _template(workspace, "email_only", app_message_enabled=False, email_enabled=True)

    msg = MessageService(workspace=workspace, user=None).send_from_template(
        [customer], "email_only", {"name": "Alice"})

    assert msg is None              # no in-app message created
    assert sent == [customer.id]    # email channel still delivered


@pytest.mark.django_db
def test_per_recipient_preferences_not_gated_by_first(workspace, monkeypatch):
    """Regression: the first recipient's opt-out used to suppress the channel for everyone."""
    sent = []
    monkeypatch.setattr(MessageService, "_send_email",
                        lambda self, recipient, *a, **k: sent.append(recipient.id))
    opted_out = _customer(workspace, "bob", email="bob@example.com", email_pref=False)   # first
    opted_in = _customer(workspace, "amy", email="amy@example.com", email_pref=True)
    _template(workspace, "evt", app_message_enabled=False, email_enabled=True)

    MessageService(workspace=workspace, user=None).send_from_template(
        [opted_out, opted_in], "evt", {"name": "x"})

    assert sent == [opted_in.id]    # only the opted-in recipient, despite being second


@pytest.mark.django_db
def test_app_message_path_still_creates_inbox_message(workspace):
    customer = _customer(workspace, "carol", email="carol@example.com")
    _template(workspace, "evt_app", app_message_enabled=True, email_enabled=False)

    msg = MessageService(workspace=workspace, user=None).send_from_template(
        [customer], "evt_app", {"name": "Carol"})

    assert msg is not None
    assert msg.subject == "Hi Carol"
    assert msg.recipients.filter(recipient=customer).exists()


# ---------------------------------------------------------------------------
# Channel registry seam (WI-420)
# ---------------------------------------------------------------------------
def test_builtin_channels_registered():
    """email/SMS/push are registered as built-in channels out of the box."""
    names = [c.name for c in MessageService.get_channels()]
    assert {"email", "sms", "push"}.issubset(set(names))


@pytest.mark.django_db
def test_registered_extra_channel_dispatched_per_recipient(workspace):
    """An extension-registered channel is invoked per recipient, gated by its
    own opt-in logic (regression coverage for the seam)."""
    from bfg.inbox.services.message_service import ChannelSender

    calls = []

    class DummyChannel(ChannelSender):
        name = "dummy"

        def __init__(self, opted_in_ids):
            self.opted_in_ids = opted_in_ids

        def template_enabled(self, template):
            return True

        def recipient_enabled(self, recipient):
            return recipient.id in self.opted_in_ids

        def send(self, service, recipient, template, context_data, subject, message, action_url):
            calls.append(recipient.id)

    opted_in = _customer(workspace, "wx_in", email="in@example.com")
    opted_out = _customer(workspace, "wx_out", email="out@example.com")
    _template(workspace, "wx_evt", app_message_enabled=True)

    MessageService.register_channel(DummyChannel({opted_in.id}))
    try:
        MessageService(workspace=workspace, user=None).send_from_template(
            [opted_in, opted_out], "wx_evt", {"name": "x"})
    finally:
        MessageService.unregister_channel("dummy")

    assert calls == [opted_in.id]  # extra channel called per-recipient; opt-out skipped


@pytest.mark.django_db
def test_registered_extra_channel_skipped_when_disabled(workspace):
    """A registered channel reporting template_enabled=False is not dispatched."""
    from bfg.inbox.services.message_service import ChannelSender

    calls = []

    class DisabledChannel(ChannelSender):
        name = "disabled"

        def template_enabled(self, template):
            return False

        def recipient_enabled(self, recipient):
            return True

        def send(self, service, recipient, template, context_data, subject, message, action_url):
            calls.append(recipient.id)

    customer = _customer(workspace, "wx_off", email="off@example.com")
    _template(workspace, "wx_off_evt", app_message_enabled=True)

    MessageService.register_channel(DisabledChannel())
    try:
        MessageService(workspace=workspace, user=None).send_from_template(
            [customer], "wx_off_evt", {"name": "x"})
    finally:
        MessageService.unregister_channel("disabled")

    assert calls == []  # channel off for the template -> never invoked


# ---------------------------------------------------------------------------
# Template lookup: platform fallback and language order
# ---------------------------------------------------------------------------
def _workspace_language(workspace, language):
    from bfg.common.models import Settings

    Settings.objects.update_or_create(workspace=workspace, defaults={"default_language": language})


@pytest.mark.django_db
def test_missing_template_raises_template_not_found(workspace):
    from bfg.core.exceptions import ValidationError
    from bfg.inbox.exceptions import TemplateNotFound

    customer = _customer(workspace, "dan")

    with pytest.raises(TemplateNotFound) as raised:
        MessageService(workspace=workspace, user=None).send_from_template([customer], "nope", {})

    assert isinstance(raised.value, ValidationError)  # what callers caught before


@pytest.mark.django_db
def test_platform_template_used_when_workspace_has_none(workspace):
    customer = _customer(workspace, "erin")
    _template(None, "evt_platform", app_message_enabled=True)

    msg = MessageService(workspace=workspace, user=None).send_from_template(
        [customer], "evt_platform", {"name": "Erin"})

    assert msg.subject == "Hi Erin"
    assert msg.workspace == workspace


@pytest.mark.django_db
def test_workspace_template_wins_over_platform(workspace):
    _template(None, "evt_both", app_message_title="Platform")
    own = _template(workspace, "evt_both", app_message_title="Shop")

    assert MessageService(workspace=workspace, user=None).get_template("evt_both") == own


@pytest.mark.django_db
def test_switched_off_workspace_template_does_not_fall_back_to_platform(workspace):
    """Switching a shop's template off turns the notification off; it must not
    quietly start sending the platform copy instead."""
    _template(None, "evt_off")
    _template(workspace, "evt_off", is_active=False)

    assert MessageService(workspace=workspace, user=None).get_template("evt_off") is None


@pytest.mark.django_db
@pytest.mark.parametrize("requested, workspace_language, expected", [
    ("zh-hans", "en", "zh-hans"),  # the recipient's language first
    ("fr", "zh-hans", "zh-hans"),  # no copy in it: the workspace default
    ("fr", "de", "en"),            # neither: English
    (None, "zh-hans", "zh-hans"),  # no recipient language: the workspace default
    ("zh-Hans", "en", "zh-hans"),  # codes compare case-insensitively
])
def test_template_language_order(workspace, requested, workspace_language, expected):
    _workspace_language(workspace, workspace_language)
    _template(workspace, "evt_lang", language="en")
    _template(workspace, "evt_lang", language="zh-hans")

    template = MessageService(workspace=workspace, user=None).get_template("evt_lang", requested)

    assert template.language == expected


@pytest.mark.django_db
def test_platform_templates_follow_the_same_language_order(workspace):
    _workspace_language(workspace, "zh-hans")
    _template(None, "evt_platform_lang", language="en")
    _template(None, "evt_platform_lang", language="zh-hans")

    template = MessageService(workspace=workspace, user=None).get_template("evt_platform_lang")

    assert template.language == "zh-hans"
