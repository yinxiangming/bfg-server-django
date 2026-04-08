# Schema-driven UI (Admin and Account)

For **Admin** and **Account** areas, prefer the schema-driven components over hand-written MUI tables and forms unless there is a strong reason not to.

## Components

- **Lists** — Configure a `ListSchema` (or equivalent list schema type used in the client) and render with `<SchemaTable endpoint="/api/v1/..." />` (or the project’s wrapper).
- **Forms** — Configure a `FormSchema` and render with `<SchemaForm />`.

## Where to look in the client

Schema types and field definitions typically live under `src/client/src/types/` (e.g. `schema.ts` or adjacent modules). Exact filenames may shift between releases; search for `SchemaTable` / `SchemaForm` imports in `src/client/src/views/admin` and `src/client/src/views/account`.

## Cursor skill

The Cursor skill **`bfg-schema`** (if installed in the user’s environment) contains deeper patterns for SchemaTable, SchemaForm, filters, and config editors.
