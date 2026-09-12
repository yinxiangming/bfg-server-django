"""send_notification: what gets retried, what does not, and which language goes out."""
import logging

import pytest

from bfg.inbox.services.message_service import MessageService
from bfg.inbox.tasks import send_notification


@pytest.fixture
def workspace(db):
    from bfg.common.models import Workspace

    return Workspace.objects.create(name="ACME", slug="acme-notify-task")


@pytest.fixture
def customer(workspace):
    from bfg.common.models import Customer, User
    from bfg.common.models.preferences import UserPreferences

    user = User.objects.create(username="buyer", email="buyer@example.com")
    UserPreferences.objects.create(user=user)
    return Customer.all_objects.create(workspace=workspace, user=user, customer_number="buyer")


def _template(workspace, language="en", **overrides):
    from bfg.inbox.models import MessageTemplate

    fields = dict(
        workspace=workspace, name="Order created", code="order_created", event="order.created",
        language=language, is_active=True, app_message_enabled=True,
        app_message_title="Order placed", app_message_body="Thanks",
    )
    fields.update(overrides)
    return MessageTemplate.objects.create(**fields)


def _run(workspace, customer):
    # apply() runs the task in-process with a real request; throw=False hands a
    # failure back as a result rather than raising it.
    return send_notification.apply(kwargs=dict(
        workspace_id=workspace.id, customer_id=customer.id,
        template_code="order_created", context_data={},
    ), throw=False)


@pytest.mark.django_db
def test_missing_template_is_logged_once_and_not_retried(workspace, customer, caplog):
    """Regression: every order in a shop without templates was retried with backoff."""
    caplog.set_level(logging.INFO, logger="bfg.inbox.tasks")

    result = _run(workspace, customer)

    assert result.successful()
    records = [r for r in caplog.records if r.name == "bfg.inbox.tasks"]
    assert [r.levelno for r in records] == [logging.WARNING]
    assert "order_created" in records[0].getMessage()


@pytest.mark.django_db
def test_transient_failure_is_still_retried(workspace, customer, monkeypatch):
    class RetryRequested(Exception):
        pass

    retries = []

    def provider_down(self, *args, **kwargs):
        raise ConnectionError("provider unavailable")

    def record_retry(*args, **kwargs):
        retries.append(kwargs)
        raise RetryRequested()

    monkeypatch.setattr(MessageService, "send_from_template", provider_down)
    # Assert the retry request, not Celery's eager replay of it: the replay runs a
    # fresh apply() under task_eager_propagates, which the project's settings decide.
    monkeypatch.setattr(send_notification._get_current_object(), "retry", record_retry)

    result = _run(workspace, customer)

    assert result.failed()
    assert len(retries) == 1
    assert isinstance(retries[0]["exc"], ConnectionError)


@pytest.mark.django_db
def test_email_only_template_is_not_retried_and_resent(workspace, customer, monkeypatch):
    """Regression: the success log read send_email off the None message, and the
    retry that followed sent the email again."""
    sent = []
    monkeypatch.setattr(MessageService, "_send_email",
                        lambda self, recipient, *a, **k: sent.append(recipient.id))
    _template(workspace, app_message_enabled=False, email_enabled=True,
              email_subject="Order placed", email_body="Thanks")

    result = _run(workspace, customer)

    assert result.successful()
    assert sent == [customer.id]


@pytest.mark.django_db
@pytest.mark.parametrize("user_language, subject", [
    ("zh-hans", "下单成功"),
    # The recipient's language outranks the shop's, and User.language defaults to 'en'.
    ("en", "Order placed"),
])
def test_recipients_language_is_used(workspace, customer, user_language, subject):
    from bfg.common.models import Settings
    from bfg.inbox.models import MessageRecipient

    Settings.objects.update_or_create(workspace=workspace, defaults={"default_language": "zh-hans"})
    customer.user.language = user_language
    customer.user.save(update_fields=["language"])
    _template(workspace, language="en", app_message_title="Order placed")
    _template(workspace, language="zh-hans", app_message_title="下单成功")

    _run(workspace, customer)

    received = MessageRecipient.objects.select_related("message").get(recipient=customer)
    assert received.message.subject == subject
