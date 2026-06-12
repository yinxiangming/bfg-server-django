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
