# Durable email outbox v1

Server baseline `544d4fffa844eafb0c6cb38ca5ba5d68d36dd763`.
Contract version `1.0.0`. The implementation belongs to BFG Common.
Dispatch record `bfg2/bfg/docs/email-outbox-dispatch.json`.

## Submission

`EmailService.enqueue_email(workspace, to_list, subject, body_plain,
body_html=None, from_email=None, attachments=None, dedupe_key=None)` persists
an immutable message and its attachment bytes in one transaction. Each queued
message has exactly one envelope recipient. Callers submit one intent per
recipient to avoid partial-recipient failures replaying accepted recipients.
An attachment is an `EmailAttachment(filename, content, content_type)` value.
The combined attachment size is limited to 10 MiB by default, configurable with
`BFG_EMAIL_MAX_ATTACHMENT_BYTES`. The body limit is 2 MiB. Up to 20 attachments
are allowed. File paths and remote attachment URLs are not accepted.

An optional workspace-scoped deduplication key returns the existing intent
when its payload is identical. A changed payload with the same key is rejected.
The key identifies a specific send request, including the document version.
An intentional resend uses a new key. Retrying an existing message keeps its
original bytes, recipient, key and Message-ID.

Submission does not need an active mail configuration or a working broker.
An on-commit notification wakes a worker when possible. The database remains
the authoritative queue. Existing `send_email` callers retain synchronous
behavior and can explicitly opt into this durable contract.

## Processing and recovery

`process_email_outbox` is both a management command and a Celery task. Beat
invokes it every minute. Deployments without Beat must schedule the command.
Workers claim eligible rows with an atomic conditional update and a lease.
Network operations occur outside database transactions. A crashed worker's
expired lease is recoverable. Late results cannot overwrite a newer claim.
Each attempt is retained, including abandoned attempts.
Inactive workspaces retain their waiting messages until they are reactivated.

Failures remain in `retry`, with exponential backoff from 60 seconds to one
hour and no automatic attempt limit. Fixing configuration or provider access
allows the next attempt to proceed. Manual retry makes a waiting message due.
An active claim and a successfully sent message cannot be manually retried.
Provider exception text, credentials and message bodies are excluded from
public status responses and error logs.

`sent` means the configured transport accepted the message. It does not mean
the recipient read it or that a bank payment was received. A transport may
accept a message immediately before a worker crashes. Recovery is at-least-once
and may send that message again. A stable Message-ID helps correlation but
does not guarantee recipient-side deduplication.

## Access

`GET /api/v1/email-outbox/` and `GET /api/v1/email-outbox/{id}/` expose
workspace-admin status, recipient, subject, attachment metadata and attempts.
List filters include `state`, `q`, `page` and `page_size` (maximum 100).
Attempt history is omitted from list rows. Detail and retry responses include
the latest 100 attempts, newest first. `attempt_count` retains the full count.
Status queries omit attachment contents and email bodies.
`POST /api/v1/email-outbox/{id}/retry/` requests an eligible retry.
Anonymous users, customers and non-admin staff have no access. Cross-workspace
IDs return 404. There is no generic public submission endpoint.

## Compatibility and migration

The new outbox models have no dependency on Inbox message or customer records.
Inbox messages require customers and track in-app read state. They cannot
represent independent mail recipients, immutable attachments or transport
attempts. Existing Inbox and synchronous email contracts remain available.
SMTP and Mailgun gain optional attachment and Message-ID support. Existing
custom backends receive their original arguments for synchronous calls without
these options. Queued delivery requires support for the extended arguments.
The additive migration does not rewrite historical messages or invoices.
