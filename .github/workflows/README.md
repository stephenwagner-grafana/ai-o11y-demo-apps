# GitHub Actions workflows

CI for `ai-o11y-demo-apps`. Public repo, images published to GHCR.

## Workflows

### `build.yml` — build & publish container images

- **Triggers**: push to `main`, pull request to `main`, manual `workflow_dispatch`.
- **Strategy**: matrix fan-out, one job per component, all in parallel. `fail-fast: false` so one broken Dockerfile doesn't cancel the rest.
- **Components built** (11 total):
  - `gateway` (context: `gateway/`)
  - `neoncart-web`, `neoncart-chatbot`, `neoncart-gift-finder` (context: `apps/<name>/`)
  - `supportbot-web`, `supportbot-router`, `supportbot-billing`, `supportbot-tech-support`, `supportbot-account-management` (context: `apps/<name>/`)
  - `postgres-seed-loader` (context: `postgres/seed-loader/`)
  - `loadgen` (context: `loadgen/`)

  Components whose context directory does not exist yet are skipped with a notice (the repo is being built in flight).

- **Platforms**: `linux/amd64,linux/arm64` (multi-arch — Apple Silicon dev).
- **Cache**: `type=gha` per-component scope (so components don't fight over cache slots).
- **Pushing**:
  - PRs: build only, no push (validates Dockerfile changes).
  - Push to `main`: push with tags `latest`, `sha-<short>`.
  - Push to other branches (via `workflow_dispatch`): push with tags `<branch-name>`, `sha-<short>`.
- **Images**: `ghcr.io/stephenwagner-grafana/ai-o11y-demo-apps/<image>:<tag>`.

> First-time setup: after the first successful push to `main`, set each
> package's visibility to **Public** in the GHCR UI
> (`https://github.com/orgs/stephenwagner-grafana/packages`) so `helm install`
> can pull without auth.

### `lint.yml` — quick code/config checks

- **Triggers**: push to `main`, pull request to `main`, manual `workflow_dispatch`.
- **Jobs**:
  1. `ruff` — Python lint across `gateway/`, `apps/`, `postgres/`, `loadgen/`, `tools/`. Soft-fails (warning only) until a `ruff.toml` / `pyproject.toml` is added; once one exists the job becomes strict automatically.
  2. `hadolint` — Dockerfile lint over every `Dockerfile*` in the repo (recursive).
  3. `yamllint` — self-check on `.github/workflows/*.yml` using a relaxed profile that tolerates the standard Actions YAML quirks (`on:` truthy, long lines).

No unit-test job yet — there are no tests in the repo.

## Dependabot (`.github/dependabot.yml`)

Weekly PRs (Monday) for:
- GitHub Actions versions (one entry).
- `pip` per Python package directory (gateway + 8 apps).
- `docker` base-image updates per Dockerfile directory.

Limit of 3-5 open PRs per ecosystem to avoid noise.

## Permissions

Workflows declare least-privilege permissions inline:
- `contents: read` for all jobs.
- `packages: write` only on the build job (needed to push to GHCR).

## Tips

- Re-run a single failed matrix entry: open the run → expand the failed job → "Re-run failed jobs".
- Skip CI on a commit: include `[skip ci]` in the commit message (GitHub built-in).
- Force a multi-arch rebuild ignoring cache: bump a no-op in the Dockerfile or push an empty commit; cache key is per-component scope.
