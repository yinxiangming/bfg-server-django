from bfg.inbox.services.message_service import MessageService


def test_render_template_replaces_context():
    service = MessageService(workspace=None, user=None)
    rendered = service._render_template("Hello {{ name }}", {"name": "BFG"})
    assert rendered == "Hello BFG"
