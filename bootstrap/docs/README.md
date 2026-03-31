# BFG app bootstrap

Run from a checkout of this repo (so templates ship with the script):

```bash
cd /path/to/parent
bash /path/to/resale/src/server/bootstrap/bootstrap-app.sh
```

Optional:

- `BOOTSTRAP_DIR` — override directory that contains `templates/`, `scripts/`, `docker/`, `openai/`.
- `SKIP_GIT_INIT=1` — skip `git init` in the new app root.
- `SKIP_DOCKER=1` — never start Docker services.
- `INIT_ADMIN_PASSWORD` — if set, `manage.py init` runs non-interactively with this password.
- `INIT_ADMIN_USERNAME` — optional admin username for non-interactive init (default: `admin`).

After creation, open the new app folder in VS Code and use tasks to run server/client.

## curl install

Pure `curl | bash` cannot access bundled `templates/` unless you download a tarball or clone the repo. Recommended:

```bash
git clone <your-resale-fork-or-mirror>.git resale && cd resale
bash src/server/bootstrap/bootstrap-app.sh
```

One-line installer is available via `install.sh` (it downloads the bundle first):

```bash
curl -fsSL "<raw-install-sh-url>" | \
  BUNDLE_URL="https://github.com/<org>/<repo>/archive/refs/heads/main.tar.gz" bash
```

For `yinxiangming/bfg-server-django` main branch (uses default BUNDLE_URL):

```bash
curl -fsSL "https://raw.githubusercontent.com/yinxiangming/bfg-server-django/main/bootstrap/install.sh" | bash
```

## OpenAI

- Server endpoint: `POST /api/v1/<slug>/ai/analyze/` with JSON `{"text":"..."}`.
- CLI: `python3 src/server/bootstrap/openai/analyze_cli.py "your idea"` with `OPENAI_API_KEY` set.

## Optional Docker services

Compose file: `bootstrap/docker/docker-compose.yml` (Redis, Mailpit, MySQL, PostgreSQL profiles). The bootstrap script can start missing dependencies when you opt in.
