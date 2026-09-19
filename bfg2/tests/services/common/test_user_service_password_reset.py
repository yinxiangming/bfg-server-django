from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings

from bfg.common.services.user_service import UserService


User = get_user_model()


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="no-reply@example.test",
    SITE_NAME="Idlevo UAT",
)
def test_request_password_reset_sends_a_django_token_link(db):
    user = User.objects.create_user(
        username="reset-recipient", password="before-reset", email="recipient@example.test",
    )

    sent = UserService.request_password_reset(user.email, "https://uat.idlevo.com")

    assert sent is True
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [user.email]
    assert mail.outbox[0].subject == "Password reset for Idlevo UAT"
    assert "https://uat.idlevo.com/reset-password?uid=" in mail.outbox[0].body
