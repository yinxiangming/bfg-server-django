# Feature: Workspace Setup Wizard

Not to be confused with [email-first onboarding](./email-first-onboarding.md), which
covers *account creation* — registering a user and provisioning their first
workspace. This is what happens after that: an existing workspace whose owner
now has to fill in a currency, a tax rate, a privacy policy and a navigation
menu before anyone can buy anything.

## Why

`manage.py provision_workspace` already knows what a workspace is missing and can
fill most of it in — but it is a command, run by an operator. The shop's owner
had no equivalent: the same twenty settings were spread across
`/admin/settings/{general,store,finance,delivery,web}` with nothing saying which
mattered, which were done, or which order to do them in.

## Shape

**One checklist, defined once.** `bfg/common/onboarding/checklist.py` declares
every item: a label, a deep link into the admin, whether it is required, and a
predicate. `GET /api/v1/onboarding/status/` serialises the whole list and the
admin renders what it is sent, so the UI and the server cannot drift.

**A country + industry template.** `bfg/common/onboarding/templates.py` merges
`data/base.json` (legal pages, menus) with the country profile in `catalog.py`
(currency, timezone, tax, jurisdiction) and `data/industry/<key>.json`
(categories, storefront display policy). Placeholders — `{{ site_name }}`,
`{{ contact_email }}`, `{{ jurisdiction }}` — are rendered per language.

**Apply is non-destructive.** This is the whole point of `service.py`.
`SiteConfigService.load_from_config` is an importer: `_upsert_page` is an
`update_or_create` and `_upsert_menu` deletes every `MenuItem` before rebuilding
it. Correct for importing a curated site config, catastrophic for a wizard
someone runs twice. So `OnboardingService` computes what is genuinely missing
first and only hands *that* over — and `POST /onboarding/preview/` shows the
user the same filtered list before anything is written.

It also never passes a `site` key, because `_upsert_site` invents the hostname
`xmart-sales.local` when given none and registers it as the workspace's primary
verified domain. The `web.Site` row is created separately, and only once the
workspace has a hostname of its own.

## API

All under `/api/v1/onboarding/`. Reads need any active staff member; writes need
workspace admin.

| Endpoint | Purpose |
|---|---|
| `GET status/` | Checklist, per-step and overall percentage, saved state |
| `GET options/` | Countries, industries, languages |
| `POST preview/` | What `apply` would create — writes nothing |
| `POST apply/` | Create everything missing; returns the recomputed status |
| `POST skip/` | `{"item": "launch.domain", "skipped": true}` |
| `POST dismiss/` | Stop showing the dashboard block |

State lives in `Settings.custom_settings.onboarding` — no migration.

## Extensions contribute to the same wizard

BFG ships the checklist every shop needs. A deployment always has more — this
codebase adds marketplace channels, address lookup, WeChat identity and a legacy
importer — and none of that belongs in a library other installs use without it.

**Server.** An installed app drops `<app>/onboarding_setup.py`; discovery is by
convention (`bfg/common/onboarding/extensions.py`), the same as
`dashboard_extensions`. Nothing to register, and an app that is not installed
contributes nothing rather than leaving a dead row.

```python
# extensions/channels-server/onboarding_setup.py
from bfg.common.onboarding.checklist import Item

ONBOARDING_ITEMS = {
    'launch': [                       # into a step BFG already defines
        Item(key='channels.connected', label='Marketplace channel connected',
             label_zh='已连接销售渠道', href='/admin/channels',
             check=lambda facts: _has_active_channel(facts.workspace),
             required=False),
    ],
}
```

Five optional hooks:

| | |
|---|---|
| `ONBOARDING_ITEMS` | `{step_key: [Item, ...]}` — rows into an existing step. An unknown step key becomes its own step rather than being dropped. |
| `ONBOARDING_STEPS` | `[Step, ...]` — a whole step of the app's own. |
| `get_custom_settings_patch(plan, workspace)` | Pre-fill the app's own `custom_settings` block from the country/industry pick. Only keys the workspace has not set are written, so deriving a country never wipes a pasted API key. |
| `ONBOARDING_INDUSTRIES` | Extra entries in the wizard's industry dropdown, appended after BFG's own. |
| `get_template_fragment(country, industry, plan)` | Contribute to the template itself — categories, pages, menus, storefront display defaults, `checklist_skip`. This is how an app ships an industry BFG has never heard of; a consignment shop's category tree does not belong in a library most installs use without one. |

Fragments merge by kind, not blindly: `categories` / `pages` / `menus` append and
are de-duplicated on `(slug, language)` — the tuple those tables are unique on,
so a fragment cannot create a second row for a slug the base template already
emits. Rows in a language the workspace does not render are dropped.
`shop_settings` merges key-by-key and `checklist_skip` unions; anything else
overrides, because a contributing app is more specific than the library default.
A provider that raises is logged and skipped.

Item keys must be namespaced by the app (`channels.connected`), because the
checklist is a flat key space and `skip` addresses rows by key. A provider that
raises is logged and skipped — third-party code must not be able to take the
checklist down.

**Client.** The wizard page registers slots `SetupProgress`, `QuickStart` and
`Checklist` under the page id `admin/setup`, and a plugin can also mount inside
one step by targeting `SetupStep:<stepKey>` — so "connect TradeMe" renders
directly under the row that says it is not connected:

```ts
sections: [
  { id: 'channels-setup-panel', page: 'admin/setup', position: 'after',
    targetSlot: 'SetupStep:launch', component: ChannelSetupPanel },
]
```

Slot components receive `{ status, onChange }` (page level) or
`{ step, onChange }` (step level).

## Adding to the checklist

Add an `Item` to the relevant `Step` in `checklist.py`. Give it a `href` that
includes the settings page's `?tab=` (the shells read it on mount via
`useTabQueryParam`), and set `from_template=True` only if `apply` actually
creates it — a test asserts that every such item goes green after an apply.

## Percentages

Only **required** items count. Skipped items count as satisfied: the user made a
decision, and a checklist that keeps nagging about a decision already made is a
checklist people stop reading. The percentage is clamped to 99 while anything is
outstanding, so "100%" never appears above a red row.
