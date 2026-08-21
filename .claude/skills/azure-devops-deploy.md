---
description: Stand up a BFG-based project on Azure DevOps — repo structure, local dev environment, pushing submodules, and a manual CI/CD pipeline that deploys the API to Dokku and the client to Vercel for UAT/prod.
trigger: when the user asks to migrate/set up a BFG project on Azure DevOps, create AzDO repos, build a deploy pipeline, or wire up uat/prod deployment.
---

# Azure DevOps deployment for a BFG monorepo

A BFG project is a thin **parent monorepo** that composes the shared framework
(`bfg-server-django`, `bfg-client-react`) with **project-specific extensions** via
git submodules + symlinks. This skill explains how to host that layout on Azure
DevOps (AzDO) and deploy it: **API → Docker image → Dokku**, **client → Vercel**.

Throughout, fill in these placeholders (set them as shell vars to copy/paste the commands):

```bash
ORG="https://dev.azure.com/<your-azdo-org>"   # e.g. https://dev.azure.com/contoso
PROJECT="<azdo-project>"                        # AzDO project name, e.g. acme
PROJ="<proj-slug>"                              # short slug used in repo/app names, e.g. acme
GH_OWNER="<github-owner>"                        # owner of the public BFG core repos

# API hosting (Dokku)
UAT_DOKKU_HOST="<uat-host-or-ip>";   UAT_SSH_USER="<uat-ssh-user>";   UAT_APP="${PROJ}-uat"
PROD_DOKKU_HOST="<prod-host-or-ip>"; PROD_SSH_USER="<prod-ssh-user>"; PROD_APP="${PROJ}"

# Client hosting (Vercel)
VERCEL_ORG_ID="<team_xxx>"; VERCEL_PROJECT_ID="<prj_xxx>"
VERCEL_UAT_ALIAS="<proj>-git-main-<team>.vercel.app"   # stable preview alias (optional)
```

Prereqs: `az` CLI with the `azure-devops` extension (`az extension add --name azure-devops`),
logged in (`az login`); `gh` for the public GitHub core repos; Docker; an SSH key that can
reach each Dokku host; a Vercel **`vcp_` API token** (see §6).

---

## 1. Repo & submodule layout (the model)

The parent monorepo holds **only** glue (compose file, scripts, `.gitmodules`, the deploy
Dockerfile, `azure-pipelines.yml`). Everything else is a submodule:

| Path in parent | Submodule repo | Hosted on | Why |
|---|---|---|---|
| `src/server` | `bfg-server-django` | **public GitHub** (`$GH_OWNER`) | shared framework core, reused by every project |
| `src/client` | `bfg-client-react` | **public GitHub** (`$GH_OWNER`) | shared framework core |
| `extensions/$PROJ-server` | `$PROJ-server` | **AzDO** (`$PROJECT`) | this project's Django app |
| `extensions/$PROJ-client` | `$PROJ-client` | **AzDO** (`$PROJECT`) | this project's Next.js plugin |
| `$PROJ-website` *(optional)* | `$PROJ-website` | **AzDO** (`$PROJECT`) | marketing/platform site |

Code is **edited** under `extensions/` but **runs** from `src/...` via symlinks:

```bash
# Django app: src/server discovers apps/<proj> automatically
ln -s ../../extensions/$PROJ-server  src/server/apps/$PROJ
# Next.js plugin
ln -s ../../../../extensions/$PROJ-client  src/client/src/plugins/$PROJ
```

Keep the framework core on **public GitHub** (so any CI can clone it anonymously) and only
the project-private repos on AzDO. This matches the "one AzDO project = parent + extensions"
convention and keeps `bfg-server-django` / `bfg-client-react` shareable across projects.

---

## 2. Local development environment

```bash
# 1. clone the parent monorepo
git clone "$ORG/$PROJECT/_git/$PROJ"  $PROJ && cd $PROJ

# 2. init submodules (BFG core is public GitHub; the AzDO subs use your az/ssh creds)
git submodule update --init --recursive

# 3. create the symlinks (see §1) — usually wrapped in a make target or scripts/setup
make setup   # or run the ln -s commands above

# 4. backend env: src/server/.env (no .env.example — create from the team template)
#    DATABASE_URL=sqlite:///dev.sqlite3   # local; prod uses MySQL (see §9 mysqlclient note)
#    SECRET_KEY=...  FRONTEND_URL=http://localhost:3000

# 5. run
docker compose up -d            # or:
( cd src/server && uv run python manage.py migrate && uv run python manage.py runserver 0.0.0.0:8000 )
( cd src/client && npm install && npm run dev )
```

---

## 3. Create the AzDO repos and push code

The AzDO **project** is assumed to exist (`az devops project create -p "$PROJECT" --org "$ORG"`
if not). Create one repo per project-private submodule (the parent repo `$PROJ` too if missing):

```bash
for r in "$PROJ" "$PROJ-server" "$PROJ-client" "$PROJ-website"; do
  az repos create --org "$ORG" -p "$PROJECT" --name "$r" \
    --query '{name:name,sshUrl:sshUrl}' -o json
done
```

Push each existing local repo (full history + tags), then set the default branch. Run from
inside each submodule working tree (and the parent):

```bash
# inside e.g. extensions/<proj>-server
git remote add azdo "git@ssh.dev.azure.com:v3/<your-azdo-org>/$PROJECT/$PROJ-server"
git push azdo --all && git push azdo --tags
az repos update --org "$ORG" -p "$PROJECT" -r "$PROJ-server" --default-branch main
```

> The parent records each submodule by **commit SHA** (gitlink), independent of branch — any
> pushed branch that contains the pinned SHA is enough. Verify before relying on a deploy:
> `git ls-tree HEAD <submodule-path>` then confirm that SHA exists in the AzDO repo.

---

## 4. Parent `.gitmodules` (mixed AzDO + GitHub)

In the parent repo, point the project-private submodules at AzDO and keep BFG core on GitHub:

```ini
[submodule "src/server"]
	path = src/server
	url = https://github.com/<github-owner>/bfg-server-django.git
[submodule "src/client"]
	path = src/client
	url = https://github.com/<github-owner>/bfg-client-react.git
[submodule "extensions/<proj>-server"]
	path = extensions/<proj>-server
	url = git@ssh.dev.azure.com:v3/<your-azdo-org>/<azdo-project>/<proj>-server
[submodule "extensions/<proj>-client"]
	path = extensions/<proj>-client
	url = git@ssh.dev.azure.com:v3/<your-azdo-org>/<azdo-project>/<proj>-client
```

Commit `.gitmodules`, the deploy `Dockerfile` (§9), and `azure-pipelines.yml` (§5); push the
parent to its AzDO repo.

---

## 5. The pipeline — `azure-pipelines.yml`

Place this at the **parent repo root**. Manual trigger; pick target + scope at queue time.
It uses **native multi-repo `checkout`** for the AzDO submodules — this is required (see §7) —
and plain `git submodule update` for the public-GitHub BFG core.

```yaml
trigger: none
pr: none

parameters:
  - name: environment
    type: string
    default: uat
    values: [uat, prod]
  - name: components
    type: string
    default: both
    values: [api, client, both]

variables:
  - group: <proj>-deploy          # variable group from §6
  - name: repoRoot
    value: '$(Build.SourcesDirectory)/<proj>'   # self repo lands in a folder named after the repo
  - ${{ if eq(parameters.environment, 'prod') }}:
      - { name: dokkuHost,  value: $(DOKKU_HOST) }
      - { name: dokkuUser,  value: $(DOKKU_SSH_USER) }
      - { name: dokkuApp,   value: $(DOKKU_APP_PROD) }
      - { name: vercelEnvName, value: production }
  - ${{ if eq(parameters.environment, 'uat') }}:
      - { name: dokkuHost,  value: $(DOKKU_UAT_HOST) }
      - { name: dokkuUser,  value: $(DOKKU_UAT_SSH_USER) }
      - { name: dokkuApp,   value: $(DOKKU_APP_UAT) }
      - { name: vercelEnvName, value: preview }

resources:
  repositories:
    - repository: projServer
      type: git
      name: <azdo-project>/<proj>-server
      ref: refs/heads/main          # branch that holds the deployed commit
    - repository: projClient
      type: git
      name: <azdo-project>/<proj>-client
      ref: refs/heads/main

stages:
  - ${{ if ne(parameters.components, 'client') }}:
      - stage: DeployAPI
        dependsOn: []
        jobs:
          - job: api
            pool: { vmImage: ubuntu-latest }
            steps:
              - checkout: self
                fetchDepth: 1
              - checkout: projServer    # native checkout = the only scoped-token-safe way (§7)
                fetchDepth: 0
              - bash: |
                  set -euo pipefail
                  cd "$(repoRoot)"
                  PIN=$(git ls-tree HEAD extensions/<proj>-server | awk '{print $3}')
                  git -C "$(Build.SourcesDirectory)/<proj>-server" checkout -q "$PIN"
                  rm -rf extensions/<proj>-server && mkdir -p extensions
                  cp -a "$(Build.SourcesDirectory)/<proj>-server" extensions/<proj>-server
                  rm -rf extensions/<proj>-server/.git
                  git submodule update --init --depth 1 src/server   # public GitHub, anonymous
                displayName: Materialize submodules
              - bash: |
                  set -euo pipefail
                  cd "$(repoRoot)"
                  docker build --platform linux/amd64 -f Dockerfile -t "dokku/$(dokkuApp):latest" .
                displayName: Docker build (linux/amd64)
              - bash: |
                  set -euo pipefail
                  mkdir -p ~/.ssh
                  printf '%s\n' "$DOKKU_KEY" > ~/.ssh/dokku_ci && chmod 600 ~/.ssh/dokku_ci
                  ssh-keyscan -H "$(dokkuHost)" >> ~/.ssh/known_hosts 2>/dev/null || true
                  IMAGE="dokku/$(dokkuApp):latest"
                  docker save "$IMAGE" | ssh -i ~/.ssh/dokku_ci -o StrictHostKeyChecking=no \
                    "$(dokkuUser)@$(dokkuHost)" "sudo dokku git:load-image $(dokkuApp) $IMAGE"
                  rm -f ~/.ssh/dokku_ci
                displayName: Push image to Dokku
                env:
                  ${{ if eq(parameters.environment, 'prod') }}:
                    DOKKU_KEY: $(DOKKU_SSH_PRIVATE_KEY)
                  ${{ if eq(parameters.environment, 'uat') }}:
                    DOKKU_KEY: $(DOKKU_UAT_SSH_PRIVATE_KEY)

  - ${{ if ne(parameters.components, 'api') }}:
      - stage: DeployClient
        dependsOn: []
        jobs:
          - job: client
            pool: { vmImage: ubuntu-latest }
            steps:
              - checkout: self
                fetchDepth: 1
              - checkout: projClient
                fetchDepth: 0
              - bash: |
                  set -euo pipefail
                  cd "$(repoRoot)"
                  PIN=$(git ls-tree HEAD extensions/<proj>-client | awk '{print $3}')
                  git -C "$(Build.SourcesDirectory)/<proj>-client" checkout -q "$PIN"
                  rm -rf extensions/<proj>-client && mkdir -p extensions
                  cp -a "$(Build.SourcesDirectory)/<proj>-client" extensions/<proj>-client
                  rm -rf extensions/<proj>-client/.git
                  git submodule update --init --depth 1 --recursive src/client
                displayName: Materialize submodules
              - task: NodeTool@0
                inputs: { versionSpec: '22.x' }
              - bash: npm install --global vercel@latest
              - bash: vercel pull --yes --environment="$(vercelEnvName)" --token="$VERCEL_TOKEN"
                workingDirectory: $(repoRoot)/src/client
                env: { VERCEL_TOKEN: $(VERCEL_TOKEN), VERCEL_ORG_ID: $(VERCEL_ORG_ID), VERCEL_PROJECT_ID: $(VERCEL_PROJECT_ID) }
              - bash: |
                  set -euo pipefail
                  if [ "$(vercelEnvName)" = "production" ]; then vercel build --prod --token="$VERCEL_TOKEN";
                  else vercel build --token="$VERCEL_TOKEN"; fi
                workingDirectory: $(repoRoot)/src/client
                env: { VERCEL_TOKEN: $(VERCEL_TOKEN), VERCEL_ORG_ID: $(VERCEL_ORG_ID), VERCEL_PROJECT_ID: $(VERCEL_PROJECT_ID) }
              - bash: |
                  set -euo pipefail
                  cd "$(repoRoot)/src/client"
                  if [ "$(vercelEnvName)" = "production" ]; then
                    vercel deploy --prebuilt --archive=tgz --prod --token="$VERCEL_TOKEN"
                  else
                    url="$(vercel deploy --prebuilt --archive=tgz --token="$VERCEL_TOKEN")"
                    echo "Preview: $url"
                    [ -n "${VERCEL_UAT_ALIAS:-}" ] && vercel alias set "$url" "$VERCEL_UAT_ALIAS" --token="$VERCEL_TOKEN"
                  fi
                displayName: Vercel deploy
                env: { VERCEL_TOKEN: $(VERCEL_TOKEN), VERCEL_ORG_ID: $(VERCEL_ORG_ID), VERCEL_PROJECT_ID: $(VERCEL_PROJECT_ID), VERCEL_UAT_ALIAS: $(VERCEL_UAT_ALIAS) }
```

> If the parent's deploy Dockerfile needs the client plugin materialized (monorepo plugin
> symlinks), insert your repo's helper scripts (e.g. `link-extensions.sh`,
> `materialize-client-plugins.sh`) before `vercel build`, run with `workingDirectory: $(repoRoot)`.

---

## 6. Variable group + secrets

Create the `<proj>-deploy` group with non-secret values, then add secrets. **Read key/token
material from files into shell vars and add with `--output none`** so it never lands in the
command text or output.

```bash
# NOTE: don't name the captured id `GID` in zsh (read-only special var) — use VGID.
VGID=$(az pipelines variable-group create --org "$ORG" -p "$PROJECT" --name "$PROJ-deploy" --authorize true \
  --variables \
    DOKKU_HOST="$PROD_DOKKU_HOST" DOKKU_SSH_USER="$PROD_SSH_USER" DOKKU_APP_PROD="$PROD_APP" \
    DOKKU_UAT_HOST="$UAT_DOKKU_HOST" DOKKU_UAT_SSH_USER="$UAT_SSH_USER" DOKKU_APP_UAT="$UAT_APP" \
    VERCEL_ORG_ID="$VERCEL_ORG_ID" VERCEL_PROJECT_ID="$VERCEL_PROJECT_ID" VERCEL_UAT_ALIAS="$VERCEL_UAT_ALIAS" \
  --query id -o tsv)

PK="$(cat ~/.ssh/<prod-deploy-key>)"
az pipelines variable-group variable create --org "$ORG" -p "$PROJECT" --group-id "$VGID" --name DOKKU_SSH_PRIVATE_KEY     --secret true --value "$PK" --output none
UK="$(cat ~/.ssh/<uat-deploy-key>)"
az pipelines variable-group variable create --org "$ORG" -p "$PROJECT" --group-id "$VGID" --name DOKKU_UAT_SSH_PRIVATE_KEY --secret true --value "$UK" --output none
az pipelines variable-group variable create --org "$ORG" -p "$PROJECT" --group-id "$VGID" --name VERCEL_TOKEN             --secret true --value "$VERCEL_TOKEN" --output none
```

**Vercel token must be a `vcp_` Personal Access Token** (vercel.com/account/tokens). The token
stored by interactive `vercel login` (`~/Library/Application Support/com.vercel.cli/auth.json`)
is an **OAuth access token** that `vercel --token` rejects — don't use it for CI. Validate a PAT:
`curl -s -o /dev/null -w '%{http_code}' https://api.vercel.com/v2/user -H "Authorization: Bearer <vcp_...>"` → 200.

---

## 7. Authorize the pipeline to read the AzDO submodule repos

AzDO projects default to **`enforceReferencedRepoScopedToken = true`**: a job's `System.AccessToken`
is scoped to only the repos it *checks out*. So an ad-hoc `git submodule update` of a **sibling
AzDO repo fails with TF401019**, even with `resources.repositories` declared. The robust fix that
does **not** weaken the global setting is the one used in §5: a **native `- checkout: projServer`**
of the repo resource (a real checkout extends the scoped token to that repo), then copy it to the
submodule path. The pipeline must also be authorized for the resource and the build identity needs
Read on the repos:

```bash
PID=$(az devops project show -p "$PROJECT" --org "$ORG" --query id -o tsv)
PIPE_ID=<pipeline-id>           # from §8
AAD=$(az account get-access-token --resource 499b84ac-1321-427f-aa17-267ca6975798 --query accessToken -o tsv)
# build-service identity descriptor (project-scoped job auth):
DESC=$(curl -s -G "https://vssps.dev.azure.com/<your-azdo-org>/_apis/identities" \
  --data-urlencode "searchFilter=General" --data-urlencode "filterValue=$PROJECT Build Service (<your-azdo-org>)" \
  --data-urlencode "api-version=7.1" -H "Authorization: Bearer $AAD" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['value'][0]['descriptor'])")

for r in "$PROJ-server" "$PROJ-client"; do
  RID=$(az repos show --org "$ORG" -p "$PROJECT" -r "$r" --query id -o tsv)
  # (a) authorize the pipeline to use the repo resource
  curl -s -X PATCH "https://dev.azure.com/<your-azdo-org>/$PROJECT/_apis/pipelines/pipelinePermissions/repository/$PID.$RID?api-version=7.1-preview.1" \
    -H "Authorization: Bearer $AAD" -H "Content-Type: application/json" \
    -d "{\"pipelines\":[{\"id\":$PIPE_ID,\"authorized\":true}]}" >/dev/null
  # (b) grant the build identity Read (bit 2) on the repo (Git Repositories namespace)
  curl -s -X POST "https://dev.azure.com/<your-azdo-org>/_apis/accesscontrolentries/2e9eb7ed-3c0a-47d4-87c1-0ffdd275fd87?api-version=7.1" \
    -H "Authorization: Bearer $AAD" -H "Content-Type: application/json" \
    -d "{\"token\":\"repoV2/$PID/$RID\",\"merge\":true,\"accessControlEntries\":[{\"descriptor\":\"$DESC\",\"allow\":2,\"deny\":0}]}" >/dev/null
done
```

> `az devops security permission update --subject` rejects the legacy service-identity descriptor
> ("descriptors element.IdentityType") — use the `accesscontrolentries` REST call above instead.

---

## 8. Create the pipeline and run it

```bash
PIPE_ID=$(az pipelines create --org "$ORG" -p "$PROJECT" --name "$PROJ-deploy" \
  --repository "$PROJ" --repository-type tfsgit --branch main \
  --yml-path azure-pipelines.yml --skip-first-run true --query id -o tsv)

# do §7 with this PIPE_ID, then run — UAT first, verify, then prod
az pipelines run --org "$ORG" -p "$PROJECT" --id "$PIPE_ID" --branch main \
  --parameters environment=uat components=api      # then components=client, then both
az pipelines run --org "$ORG" -p "$PROJECT" --id "$PIPE_ID" --branch main \
  --parameters environment=prod components=both
```

Watch a run / read a failed step's log:

```bash
az pipelines runs show --org "$ORG" -p "$PROJECT" --id <runId> --query '{status:status,result:result}' -o json
az devops invoke --org "$ORG" --area build --resource Timeline \
  --route-parameters project="$PROJECT" buildId=<runId> --api-version 7.1-preview \
  --query "records[?result=='failed'].{name:name,issues:issues[].message}" -o json
```

Verify after deploy: API `curl -s -o /dev/null -w '%{http_code}' https://<api-host>/api/docs/` → 200;
client URL responds (a Vercel-SSO project returns 401 = up-but-protected).

---

## 9. Gotchas (each cost real time)

- **Django 6 needs `mysqlclient` compiled.** Django 6's MySQL backend requires
  `mysqlclient>=2.2.1` and rejects the PyMySQL shim. The deploy `Dockerfile` (single-stage,
  `python:*-slim`) must install build deps before `pip install`:
  `apt-get install -y build-essential pkg-config default-libmysqlclient-dev`. Locally you can't
  build it without those system libs — use sqlite for local dev/tests.
- **Scoped token (§7)** — `resources.repositories` alone does not extend the job token to a
  sibling repo for `git submodule`; a native `checkout:` does. Don't disable the global
  `enforceReferencedRepoScopedToken` just to make it work.
- **Vercel `--token` needs a `vcp_` PAT (§6)**, not the CLI's stored OAuth token.
- **Submodule pin vs branch** — deploy the exact commit the parent records; the pipeline
  resolves it via `git ls-tree HEAD <path>` and `git checkout <SHA>` after the resource checkout.
- **Push submodules before deploy** — an unpushed submodule SHA makes `git:load-image`/checkout
  fail with "not our ref".
- **Hosted parallelism** — a private project gets 1 free Microsoft-hosted job (1800 min/mo); no
  grant request needed. Check: `az devops invoke --area distributedtask --resource resourcelimits`.
- **zsh** — don't capture into `GID`/`UID` (read-only special vars); use `VGID` etc.
- **Dokku zero-downtime** — a failed `release` (e.g. `migrate` or a prod self-check) keeps the
  current container running, so a bad deploy doesn't take the app down.
```
