# Extension archives

A workspace that switches an extension off keeps its rows — that is what makes switching
it back on free. After `archive_after_days` those rows are exported to private storage,
read back and checked, and only then deleted; the extension's record goes to `archived`
and says where the archive is. Reactivating one is a **restore**, which loads the rows
back and switches it on.

This deletes production data. Everything below is arranged so that it refuses rather than
guesses, and **nothing is configured by default**: until the deployment names storage to
write to, no archive is ever written and no row is ever deleted.

Code: `bfg/common/extensions/archive.py` and `bfg/common/extensions/archive_storage.py`.

---

## 1. What has to be configured

| Setting / env | Default | What it does |
|---|---|---|
| `BFG_EXTENSION_ARCHIVE_BUCKET` | *(empty)* | Bucket archives are written to. **Empty ⇒ the whole feature is off.** |
| `BFG_EXTENSION_ARCHIVE_DIR` | *(empty)* | A local directory instead of a bucket. A place to put archives, not an off-site copy — back it up yourself. |
| `BFG_EXTENSION_ARCHIVE_PREFIX` | `extension-archives` | Key prefix inside the bucket, so several deployments can share one. |
| `BFG_EXTENSION_ARCHIVE_REGION` | `AWS_S3_REGION_NAME` | Region of the archive bucket. |
| `BFG_EXTENSION_ARCHIVE_ACCESS_KEY_ID` / `_SECRET_ACCESS_KEY` | *(empty)* | A key that can write the archive bucket and nothing else. Empty falls back to the deployment's own credentials. |
| `BFG_EXTENSION_ARCHIVE_ENDPOINT_URL` | *(empty)* | For an S3-compatible store that is not AWS. |
| `BFG_EXTENSION_ARCHIVE_RESTORE_ASYNC` | `false` | Load an archive back in a Celery worker instead of while the request waits. |
| `BFG_EXTENSION_ARCHIVE_STUCK_MINUTES` | `60` | How long a run may be in flight before a sweep decides the process running it died. |

`config/settings.py` turns those into a `STORAGES` alias called `extension_archive` and
points `BFG_EXTENSION_ARCHIVE_STORAGE` at it. A deployment that builds its own `STORAGES`
can skip all of the above and set `BFG_EXTENSION_ARCHIVE_STORAGE` to any alias of its own.

### The storage must not be served

An archive holds whole tables verbatim, so a public URL to one is a data breach rather
than an inconvenience. Before every archive the configured storage is checked, and
refused when it:

* is the `default` or `staticfiles` alias, or resolves to the same storage object;
* writes to the **same bucket** as the media the deployment serves — a prefix of its own
  inside a world-readable bucket is a world-readable archive;
* has a `custom_domain` — that is how a bucket is put behind a CDN;
* is a directory inside (or containing) `MEDIA_ROOT`.

Each of those switches archiving off with a sentence saying which one it was; the sweep
prints it and stops. Nothing is written, and nothing is deleted.

### Retention is yours to set

**Nothing in this code ever deletes an archive.** Put a lifecycle rule on the archive
prefix yourself, at whatever `archive_retention_days` your deployment has agreed to
(there is a platform variable of that name, and it is a number for people to work to —
no code reads it). Until you do, archives are kept for ever, which is the failure that
costs money rather than data.

---

## 2. Which days, and from when

`archive_after_days` is a **platform variable** (default 30), not a release: change it in
the platform console. It is counted from the moment the extension became `inactive` or
`paused` — the pause an entitlement running out causes counts, so an add-on nobody paid
for is archived a month after it stopped working.

`archive_retention_days` (default 365) is the other one, and is documentation for
whoever sets the lifecycle rule.

---

## 3. Running it

There is no scheduler on these deployments — no Celery beat — so this runs from cron or
by hand, ideally once a day. Running it twice does nothing the second time.

```bash
# everything that is due
python manage.py archive_unused_extensions

# read the run before making it: same checks, same counts, writes and deletes nothing
python manage.py archive_unused_extensions --dry-run

# narrow it
python manage.py archive_unused_extensions --workspace acme --limit 5

# archive one extension of one workspace now, without waiting out the days
python manage.py archive_unused_extensions --workspace acme --key some_key --ignore-age
```

`--ignore-age` requires both `--workspace` and `--key`, so it can never mean more than one
extension of one workspace.

Restoring:

```bash
python manage.py workspace_extensions restore some_key --workspace acme
```

or from the console — `POST /api/v1/platform/console/workspaces/{id}/extensions/{key}/restore/`,
which is what a "reactivate" button calls. Activating an archived extension is refused
(`archived`): the rows are not there to activate.

There is a Celery task for each (`bfg.common.tasks.archive_unused_extensions`,
`finish_extension_restore`), and each is a wrapper around the same service the command
calls. Nothing is scheduled to run them.

---

## 4. What an archive looks like

```
<prefix>/workspace-<id>/<extension key>/<YYYYMMDDTHHMMSSZ>/
    manifest.json
    <app_label>.<ModelName>.jsonl      one per table, Django's JSON Lines serialization
```

`manifest.json`:

| Field | Meaning |
|---|---|
| `format` | Archive layout version; a reader that does not know it refuses. |
| `extension`, `workspace_id`, `workspace_slug` | Whose copy of what. Both are checked on restore. |
| `directory` | Where this archive was written. |
| `archived_at` | When. |
| `status_before`, `status_reason_before`, `status_changed_at` | The state the extension was archived out of. |
| `config` | The workspace's configuration for the extension, kept with the data. |
| `migrations` | `{app_label: last applied migration}` at the time of writing. |
| `tables[]` | Per table: `model`, `file`, `rows`, `bytes`, `checksum` (`sha256:…`). |
| `joins` | `{join table: rows}` for the many-to-many tables Django made. They are written inside the row that owns them, so they are counted rather than listed — and the delete is checked against these counts too. |
| `total_rows` | The sum, which is what the console shows. |

---

## 5. What it refuses, and what it leaves behind

Every refusal below happens **before** anything is deleted, and leaves the extension on
the status it had, with `status_reason` saying an archive failed and `archive_state`
carrying the sentence.

| Code | Why |
|---|---|
| `unscoped_model` | A table in `data_models` has no `workspace` relation, so nothing says whose rows they are. |
| `unknown_model` | `data_models` names a model this deployment does not have. |
| `outside_references` | Rows of a table the extension does not own still point at rows being archived — the delete would reach past the archive. |
| `cross_workspace_join` | A many-to-many row ties this workspace's row to another workspace's. |
| `too_soon` | Not switched off for long enough. |
| `not_archivable` | Not `inactive` or `paused`. |
| `checksum_mismatch`, `missing_file`, `manifest_mismatch` | The archive does not read back byte for byte out of storage. |
| `row_count_changed`, `deleted_outside_archive` | The delete removed something other than exactly what was exported. The delete itself is rolled back. |
| `storage_renamed_file`, `archive_exists` | Storage put a file somewhere other than where the manifest names it. |

On restore:

| Code | Why |
|---|---|
| `migrations_changed` | The app's schema has moved since the archive was written and the manifest offers no `restore_converters` entry for it. The message says which migration to which. |
| `converter_refused` | The extension's converter raised `ValueError`; its message is carried through. |
| `wrong_workspace`, `wrong_extension`, `unsupported_format` | The archive is not this workspace's copy of this extension. |
| `key_conflict` | A primary key in the archive now belongs to another workspace's row. |
| `checksum_mismatch`, `archive_missing` | The archive is not what it was, or is not there. |
| `not_archived` | The extension is not archived, so there is nothing to restore. |

### Where a failure leaves the record

```
inactive / paused ──archive──> archiving ──> archived
                        └─ failed ─> back to inactive / paused, status_reason = archive_failed
archived ──restore──> restoring ──> active
                 └─ failed ─> back to archived, status_reason = restore_failed
```

An archive that failed **does not restart the clock**: the extension keeps the
`status_changed_at` it had, so tomorrow's sweep tries again rather than waiting another
month. A persistently failing one is reported by every run.

If the process dies mid-run the record is left on `archiving` or `restoring`. The next
sweep puts anything older than `BFG_EXTENSION_ARCHIVE_STUCK_MINUTES` back —
`archiving` to the status it interrupted (the rows are still there, because they are only
ever deleted in the same transaction that writes `archived`), `restoring` to `archived`.
Releasing one that turns out to still be running is harmless: both transactions check
that the status is still theirs before writing anything.

---

## 6. What an extension has to declare

```python
EXTENSION = ExtensionManifest(
    key='some_key',
    name='Something',
    data_models=('some_app.Thing', 'some_app.ThingLine'),
    restore_converters={'some_app': convert_rows},   # optional
)
```

* Every model in `data_models` **must carry a `workspace` relation**, child tables
  included. A table without one is not archived and stops the extension being archived at
  all, which is the safe answer: the alternative is guessing which rows to delete.
* Anything the extension wrote into a core table is never touched.
* `restore_converters` maps an app label to `(archive_manifest, model_label, rows) -> rows`,
  called before loading when that app's migrations have moved since the archive was
  written. Raise `ValueError` from it to refuse with a message an administrator is shown.

---

## 7. What the console sees

Each extension in `GET /api/v1/platform/console/workspaces/{id}/` carries:

* `status` — including `archiving`, `archived` and `restoring`;
* `status_reason` — `archived`, `archive_failed`, `restore_failed`, `archive_interrupted`, …;
* `archive` — `archived_at`, `rows`, `tables`, `restored_at`, and `error` / `error_code` /
  `failed_at` for the last failure. `location` is in there for platform administrators
  only: an owner is shown what happened to their data, not where the deployment keeps it.
