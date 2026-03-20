from types import SimpleNamespace

from bfg.web.services.newsletter_service import NewsletterService


def test_can_send_to_blocks_unsubscribed():
    service = NewsletterService(workspace=SimpleNamespace(id=1), user=None)
    sub = SimpleNamespace(status="unsubscribed")
    newsletter_send = SimpleNamespace(id=1)

    assert service.can_send_to(sub, newsletter_send) is False
