"""Persistence, claim fencing, tenant scope and real SMTP queue regression tests."""

import json
import socketserver
import threading
import uuid
from datetime import timedelta
from email import policy
from email.parser import BytesParser
from io import StringIO
from unittest.mock import Mock

import pytest
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.test import APIClient

from bfg.common.email_backends.attachments import EmailAttachment
from bfg.common.email_outbox_api import EmailOutboxViewSet
from bfg.common.middleware import set_current_workspace
from bfg.common.models import EmailConfig, EmailOutbox, StaffMember, StaffRole, User, Workspace
from bfg.common.services import EmailService
from bfg.common.services import email_outbox
from bfg.common.services.email_outbox import _wake_worker as wake_worker

pytestmark = pytest.mark.django_db


@pytest.fixture
def workspace(monkeypatch):
    monkeypatch.setattr(email_outbox, '_wake_worker', Mock())
    return Workspace.objects.create(name='Mail workspace', slug='mail-workspace')


def enqueue(workspace, **overrides):
    return EmailService.enqueue_email(workspace, **{
        'to_list': ['recipient@example.com'], 'subject': 'Statement',
        'body_plain': 'A fixed document.', 'dedupe_key': 'document-v1-request-1',
        'attachments': [EmailAttachment('账单.pdf', b'%PDF-1.7\nfixed snapshot', 'application/pdf')],
        **overrides,
    })


def configure(workspace, **overrides):
    return EmailConfig.objects.create(
        workspace=workspace, name='Transport', is_default=True, is_active=True,
        backend_type='smtp', config={'host': '127.0.0.1', 'port': 1025,
                                     'from_email': 'sender@example.com', **overrides},
    )


def make_due(message):
    EmailOutbox.all_objects.filter(pk=message.pk).update(next_attempt_at=timezone.now())


def test_submission_is_persisted_without_config_or_broker(workspace, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        message = enqueue(workspace)
    assert message.state == 'pending'
    assert message.attachments.get().content == b'%PDF-1.7\nfixed snapshot'
    assert message.attachments.get().size == 23
    assert len(message.attachments.get().sha256) == 64
    email_outbox._wake_worker.assert_called_once()


def test_duplicate_intent_returns_one_immutable_snapshot(workspace):
    first = enqueue(workspace)
    assert enqueue(workspace).pk == first.pk
    assert first.attachments.count() == 1
    with pytest.raises(ValueError, match='different payload'):
        enqueue(workspace, subject='Changed')
    with pytest.raises(ValueError, match='different payload'):
        enqueue(workspace, attachments=[EmailAttachment('new.pdf', b'new')])
    first.refresh_from_db()
    assert first.subject == 'Statement'
    assert EmailOutbox.all_objects.count() == 1


def test_same_intent_key_is_separate_between_workspaces(workspace):
    other = Workspace.objects.create(name='Other', slug='other-mail')
    assert enqueue(workspace).pk != enqueue(other).pk


def test_intent_keys_preserve_case_and_trailing_spaces(workspace):
    first = enqueue(workspace, dedupe_key='Request-A')
    second = enqueue(workspace, dedupe_key='request-a')
    third = enqueue(workspace, dedupe_key='Request-A ')
    assert len({first.pk, second.pk, third.pk}) == 3


def test_enqueue_rollback_retains_no_partial_payload(workspace):
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            enqueue(workspace)
            raise RuntimeError('Roll back caller operation')
    assert not EmailOutbox.all_objects.exists()


@pytest.mark.parametrize('overrides', [
    {'to_list': []}, {'to_list': ['one@example.com', 'two@example.com']},
    {'to_list': ['invalid']}, {'to_list': 'recipient@example.com'},
    {'to_list': ['good@example.com\nBcc: secret@example.com']},
    {'from_email': 'invalid'}, {'subject': 'Bad\r\nHeader'}, {'subject': ''},
    {'subject': 'a' * 256}, {'body_plain': None}, {'body_html': {}},
    {'dedupe_key': ''}, {'dedupe_key': 'x' * 201},
    {'attachments': [EmailAttachment('../secret.pdf', b'bad')]},
    {'attachments': [EmailAttachment('bad\n.pdf', b'bad')]},
    {'attachments': [EmailAttachment('x.pdf', 'not bytes')]},
    {'attachments': [EmailAttachment('x.pdf', b'bad', 'bad/type\r\nHeader')]},
    {'attachments': [{'filename': 'x.pdf', 'content': b'bad'}]},
    {'attachments': [EmailAttachment('x.pdf', b'')] * 21},
])
def test_invalid_payload_never_creates_work(workspace, overrides):
    with pytest.raises(ValueError):
        enqueue(workspace, **overrides)
    assert not EmailOutbox.all_objects.exists()


def test_payload_size_limits_are_atomic(workspace, settings):
    settings.BFG_EMAIL_MAX_ATTACHMENT_BYTES = 2
    with pytest.raises(ValueError, match='size limit'):
        enqueue(workspace)
    with pytest.raises(ValueError, match='size limit'):
        enqueue(workspace, body_plain='x' * (2 * 1024 * 1024 + 1), attachments=[])
    assert not EmailOutbox.all_objects.exists()


def test_missing_configuration_is_retained_and_recovers(workspace, monkeypatch):
    message = enqueue(workspace)
    assert email_outbox.process_due()['retry'] == 1
    message.refresh_from_db()
    assert message.last_error_code == 'email_config_unavailable'
    assert message.attempt_count == 1
    assert message.next_attempt_at > timezone.now()
    assert email_outbox.process_due()['claimed'] == 0
    configure(workspace)
    send = Mock()
    monkeypatch.setattr(EmailService, 'send_email', send)
    make_due(message)
    assert email_outbox.process_due()['sent'] == 1
    message.refresh_from_db()
    assert message.sent_at is not None
    assert message.last_error_code == ''
    assert list(message.attempts.values_list('state', flat=True)) == ['failed', 'accepted']
    assert send.call_args.kwargs['attachments'][0].filename == '账单.pdf'
    assert str(message.message_id) in send.call_args.kwargs['message_id']
    assert email_outbox.process_due()['claimed'] == 0


def test_inactive_workspace_retains_work_until_reactivated(workspace):
    message = enqueue(workspace)
    Workspace.objects.filter(pk=workspace.pk).update(is_active=False)
    assert email_outbox.process_due()['claimed'] == 0
    assert email_outbox._claim(message.pk, timezone.now()) is None
    message.refresh_from_db()
    assert message.attempt_count == 0
    Workspace.objects.filter(pk=workspace.pk).update(is_active=True)
    assert email_outbox.process_due()['retry'] == 1


def test_provider_exception_text_is_not_persisted_or_exposed(workspace, monkeypatch, caplog):
    message = enqueue(workspace)
    configure(workspace)
    monkeypatch.setattr(EmailService, 'send_email', Mock(side_effect=RuntimeError('sensitive-provider-key')))
    assert email_outbox.process_due()['retry'] == 1
    message.refresh_from_db()
    assert message.last_error_code == 'email_transport_error'
    assert message.attempts.get().error_code == 'email_transport_error'
    assert 'sensitive-provider-key' not in caplog.text
    assert not email_outbox.retry_email(Workspace.objects.create(name='Other', slug='other'), message.pk)
    assert email_outbox.retry_email(workspace, message.pk)


def test_retry_has_no_attempt_limit_and_backoff_is_bounded(workspace):
    message = enqueue(workspace)
    for attempt in range(10):
        make_due(message)
        assert email_outbox.process_due()['retry'] == 1
    message.refresh_from_db()
    assert message.attempt_count == 10
    remaining = (message.next_attempt_at - timezone.now()).total_seconds()
    assert 3590 < remaining <= 3600
    assert message.attempts.count() == 10


def test_atomic_claim_prevents_active_worker_reclaim(workspace):
    message = enqueue(workspace)
    now = timezone.now()
    claimed = email_outbox._claim(message.pk, now)
    assert claimed is not None
    assert email_outbox._claim(message.pk, now) is None
    assert email_outbox.process_due()['claimed'] == 0
    assert not email_outbox.retry_email(workspace, message.pk)
    assert claimed.attempts.count() == 1


@pytest.mark.parametrize('error_code', [5, 6, 262])
def test_sqlite_busy_claim_rolls_back_and_remains_claimable(workspace, monkeypatch, error_code):
    from sqlite3 import OperationalError as SQLiteError
    from django.db import OperationalError
    from bfg.common.models import EmailOutboxAttempt

    message = enqueue(workspace)
    cause = SQLiteError('database table is locked')
    cause.sqlite_errorcode = error_code
    failure = OperationalError(str(cause))
    failure.__cause__ = cause
    with monkeypatch.context() as patch:
        patch.setattr(EmailOutboxAttempt.objects, 'create', Mock(side_effect=failure))
        assert email_outbox._claim(message.pk, timezone.now()) is None
    message.refresh_from_db()
    assert message.state == EmailOutbox.State.PENDING and message.attempt_count == 0
    assert message.attempts.count() == 0
    assert email_outbox._claim(message.pk, timezone.now()) is not None


def test_unrelated_claim_database_errors_are_not_suppressed(workspace, monkeypatch):
    from django.db import OperationalError
    from bfg.common.models import EmailOutboxAttempt

    message = enqueue(workspace)
    monkeypatch.setattr(EmailOutboxAttempt.objects, 'create', Mock(side_effect=OperationalError('unavailable table')))
    with pytest.raises(OperationalError, match='unavailable table'):
        email_outbox._claim(message.pk, timezone.now())
    message.refresh_from_db()
    assert message.state == EmailOutbox.State.PENDING and message.attempt_count == 0


@pytest.mark.django_db(transaction=True)
def test_concurrent_workers_only_obtain_one_lease(workspace):
    from concurrent.futures import ThreadPoolExecutor
    from django.db import connections

    message = enqueue(workspace)
    barrier = threading.Barrier(2)

    def claim():
        try:
            barrier.wait(timeout=10)
            return email_outbox._claim(message.pk, timezone.now()) is not None
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim), pool.submit(claim)]
        results = [future.result(timeout=15) for future in futures]
    assert sorted(results) == [False, True]
    message.refresh_from_db()
    assert message.attempt_count == 1
    assert message.attempts.count() == 1


def test_expired_worker_recovers_and_stale_completion_is_fenced(workspace, monkeypatch):
    message = enqueue(workspace)
    configure(workspace)
    first = email_outbox._claim(message.pk, timezone.now())
    EmailOutbox.all_objects.filter(pk=message.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
    recovered = email_outbox._claim(message.pk, timezone.now())
    assert recovered.lease_token != first.lease_token
    assert list(message.attempts.values_list('state', flat=True)) == ['interrupted', 'sending']
    send = Mock()
    monkeypatch.setattr(EmailService, 'send_email', send)
    assert email_outbox.deliver_claim(first) == 'superseded'
    assert email_outbox.deliver_claim(recovered) == 'sent'
    send.assert_called_once()
    assert list(message.attempts.values_list('state', flat=True)) == ['interrupted', 'accepted']
    assert not email_outbox.retry_email(workspace, message.pk)


def test_nested_worker_cannot_send_same_active_claim(workspace, monkeypatch):
    enqueue(workspace)
    configure(workspace)
    nested = []
    monkeypatch.setattr(EmailService, 'send_email', lambda *args, **kwargs: nested.append(email_outbox.process_due()))
    assert email_outbox.process_due()['sent'] == 1
    assert nested[0]['claimed'] == 0


def test_command_and_task_use_same_persisted_queue(workspace):
    enqueue(workspace)
    output = StringIO()
    call_command('process_email_outbox', workspace_id=workspace.pk, stdout=output)
    assert json.loads(output.getvalue())['retry'] == 1
    from bfg.common.tasks import process_email_outbox
    assert process_email_outbox.run()['claimed'] == 0


def test_broker_failure_never_removes_committed_intent(workspace, monkeypatch, caplog):
    from bfg.common.tasks import process_email_outbox
    monkeypatch.setattr(process_email_outbox, 'delay', Mock(side_effect=RuntimeError('secret broker url')))
    enqueue(workspace)
    wake_worker()
    assert EmailOutbox.all_objects.count() == 1
    assert 'secret broker url' not in caplog.text


def test_configuration_cannot_cross_workspace(workspace):
    other = Workspace.objects.create(name='Other', slug='other-config')
    config = configure(other)
    with pytest.raises(ValueError, match='another workspace'):
        EmailService.send_email(workspace, ['recipient@example.com'], 'Subject', 'Body', config=config)


def test_synchronous_legacy_backend_keeps_original_arguments(workspace, monkeypatch):
    config = configure(workspace)
    sent = []

    class LegacyBackend:
        def send(self, to_list, subject, body_plain, body_html, from_email, config):
            sent.append(subject)

    monkeypatch.setattr('bfg.common.services.email_service.get_backend', lambda name: LegacyBackend)
    EmailService.send_email(workspace, ['recipient@example.com'], 'Legacy', 'Body', config=config)
    assert sent == ['Legacy']


def test_mailgun_attachment_and_message_id_preserve_multipart_contract(monkeypatch):
    from bfg.common.email_backends.mailgun import MailgunBackend

    post = Mock(return_value=Mock())
    monkeypatch.setattr('bfg.common.email_backends.mailgun.requests.post', post)
    MailgunBackend().send(
        ['recipient@example.com'], 'Statement', 'Body', body_html='<p>Body</p>',
        config={'domain': 'example.com', 'api_key': 'synthetic-key', 'from_email': 'sender@example.com'},
        attachments=[EmailAttachment('statement.pdf', b'%PDF', 'application/pdf')],
        message_id='<stable@example.com>',
    )
    assert post.call_args.kwargs['files'] == [('attachment', ('statement.pdf', b'%PDF', 'application/pdf'))]
    assert post.call_args.kwargs['data']['h:Message-Id'] == '<stable@example.com>'
    assert post.call_args.kwargs['timeout'] == 30
    post.return_value.raise_for_status.assert_called_once()


def test_smtp_quit_disconnect_does_not_replay_an_accepted_message(monkeypatch):
    import smtplib
    from bfg.common.email_backends.smtp import SMTPBackend

    server = Mock()
    server.quit.side_effect = smtplib.SMTPServerDisconnected('Closed after acceptance')
    monkeypatch.setattr('bfg.common.email_backends.smtp.smtplib.SMTP', Mock(return_value=server))
    SMTPBackend().send(['recipient@example.com'], 'Subject', 'Body', config={
        'host': 'mail.invalid', 'from_email': 'sender@example.com',
    })
    server.sendmail.assert_called_once()
    server.close.assert_called_once()


def api_request(workspace, user, action='list', method='get', message_id=None, query=None):
    factory = APIRequestFactory()
    request = getattr(factory, method)('/api/v1/email-outbox/', data=query or {})
    request.workspace = workspace
    if user is not None:
        force_authenticate(request, user=user)
    set_current_workspace(workspace)
    mapping = {method: action}
    kwargs = {'pk': message_id} if message_id is not None else {}
    return EmailOutboxViewSet.as_view(mapping)(request, **kwargs)


def admin_user(workspace):
    user = User.objects.create(username='admin-mail')
    role = StaffRole.objects.create(workspace=workspace, code='admin', name='Administrator')
    StaffMember.all_objects.create(workspace=workspace, user=user, role=role)
    return user


def test_admin_api_status_filters_and_retry_are_scoped(workspace):
    user = admin_user(workspace)
    message = enqueue(workspace)
    other = Workspace.objects.create(name='Other', slug='other-api')
    other_message = enqueue(other)
    response = api_request(workspace, user, query={'state': 'pending', 'q': 'recipient'})
    assert response.status_code == 200
    assert response.data['count'] == 1
    item = response.data['results'][0]
    assert item['attachments'][0]['filename'] == '账单.pdf'
    assert 'content' not in item['attachments'][0]
    assert 'body_plain' not in item
    assert api_request(workspace, user, 'retrieve', message_id=other_message.pk).status_code == 404
    assert api_request(workspace, user, 'retry', 'post', other_message.pk).status_code == 404
    detail = api_request(workspace, user, 'retrieve', message_id=message.pk)
    assert detail.status_code == 200
    assert detail.data['attempts'] == []
    response = api_request(workspace, user, 'retry', 'post', message.pk)
    assert response.status_code == 200, response.data
    assert api_request(workspace, user, query={'state': 'unknown'}).status_code == 400
    EmailOutbox.all_objects.filter(pk=message.pk).update(state='sent', sent_at=timezone.now())
    assert api_request(workspace, user, 'retry', 'post', message.pk).status_code == 409


def test_detail_bounds_attempt_history_without_losing_full_count(workspace):
    from bfg.common.models import EmailOutboxAttempt

    user = admin_user(workspace)
    message = enqueue(workspace)
    EmailOutboxAttempt.objects.bulk_create([
        EmailOutboxAttempt(message=message, number=number, lease_token=uuid.uuid4(), state='failed')
        for number in range(1, 106)
    ])
    EmailOutbox.all_objects.filter(pk=message.pk).update(attempt_count=105)
    response = api_request(workspace, user, 'retrieve', message_id=message.pk)
    assert response.status_code == 200
    assert response.data['attempt_count'] == 105
    assert [item['number'] for item in response.data['attempts']] == list(range(105, 5, -1))


def test_default_manager_fails_closed_outside_workspace(workspace):
    enqueue(workspace)
    set_current_workspace(None)
    assert not EmailOutbox.objects.exists()
    set_current_workspace(workspace)
    assert EmailOutbox.objects.count() == 1


def test_registered_routes_work_through_session_auth_and_workspace_middleware(workspace):
    user = admin_user(workspace)
    message = enqueue(workspace)
    other = Workspace.objects.create(name='Other', slug='other-http')
    other_message = enqueue(other)
    client = APIClient()
    client.force_login(user)
    session = client.session
    session['workspace_id'] = workspace.pk
    session.save()
    response = client.get('/api/v1/email-outbox/')
    assert response.status_code == 200, response.data
    assert response.data['count'] == 1
    assert client.get(f'/api/v1/email-outbox/{other_message.pk}/').status_code == 404
    assert client.post(f'/api/v1/email-outbox/{message.pk}/retry/', {}).status_code == 200
    client.logout()
    assert client.get('/api/v1/email-outbox/').status_code in (400, 401, 403)


@pytest.mark.parametrize('identity', ['anonymous', 'customer', 'staff', 'inactive_admin'])
def test_non_admin_cannot_view_mail_status(workspace, identity):
    enqueue(workspace)
    user = None
    if identity != 'anonymous':
        user = User.objects.create(username=identity)
    if identity in ('staff', 'inactive_admin'):
        role = StaffRole.objects.create(workspace=workspace, code='admin' if identity == 'inactive_admin' else 'staff', name=identity)
        StaffMember.all_objects.create(workspace=workspace, user=user, role=role, is_active=identity != 'inactive_admin')
    assert api_request(workspace, user).status_code in (401, 403)


class SMTPHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(b'220 local verification\r\n')
        while True:
            line = self.rfile.readline()
            if not line:
                return
            verb = line.split(b' ', 1)[0].strip().upper()
            if verb == b'EHLO':
                self.wfile.write(b'250-local verification\r\n250 SIZE 20000000\r\n')
            elif verb == b'DATA':
                if self.server.reject_next:
                    self.server.reject_next = False
                    self.wfile.write(b'451 temporary failure\r\n')
                    continue
                self.wfile.write(b'354 send data\r\n')
                payload = []
                while True:
                    chunk = self.rfile.readline()
                    if chunk in (b'.\r\n', b''):
                        break
                    payload.append(chunk[1:] if chunk.startswith(b'..') else chunk)
                self.server.messages.append(b''.join(payload))
                self.wfile.write(b'250 accepted\r\n')
            elif verb == b'QUIT':
                self.wfile.write(b'221 bye\r\n')
                return
            else:
                self.wfile.write(b'250 ok\r\n')


def test_real_smtp_failure_then_recovery_sends_exact_pdf_snapshot(workspace):
    server = socketserver.TCPServer(('127.0.0.1', 0), SMTPHandler)
    server.messages = []
    server.reject_next = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        configure(workspace, port=server.server_address[1])
        message = enqueue(workspace, body_html='<p>A fixed document.</p>')
        assert email_outbox.process_due()['retry'] == 1
        assert server.messages == []
        make_due(message)
        assert email_outbox.process_due()['sent'] == 1
        assert len(server.messages) == 1
        mime = BytesParser(policy=policy.default).parsebytes(server.messages[0])
        attachment = list(mime.iter_attachments())[0]
        assert attachment.get_filename() == '账单.pdf'
        assert attachment.get_content_type() == 'application/pdf'
        assert attachment.get_payload(decode=True) == b'%PDF-1.7\nfixed snapshot'
        assert mime['Message-ID'] == f'<{message.message_id}@outbox.bfg.invalid>'
        assert mime.get_body(preferencelist=('html',)).get_content().strip() == '<p>A fixed document.</p>'
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
