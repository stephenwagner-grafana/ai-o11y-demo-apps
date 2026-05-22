#!/usr/bin/env bash
# Flip every ghcr.io container package for this repo to public visibility.
# Run once after the first successful CI build.
#
# Requires `gh` (GitHub CLI) authenticated against the user/org that owns
# the packages. Idempotent — re-running on already-public packages is a no-op.

set -euo pipefail

OWNER="${OWNER:-stephenwagner-grafana}"
PACKAGES=(
  ai-o11y-demo-apps/gateway
  ai-o11y-demo-apps/neoncart-web
  ai-o11y-demo-apps/neoncart-chatbot
  ai-o11y-demo-apps/neoncart-gift-finder
  ai-o11y-demo-apps/supportbot-web
  ai-o11y-demo-apps/supportbot-router
  ai-o11y-demo-apps/supportbot-billing
  ai-o11y-demo-apps/supportbot-tech-support
  ai-o11y-demo-apps/supportbot-account-management
  ai-o11y-demo-apps/postgres-seed-loader
  ai-o11y-demo-apps/loadgen
)

# ── output helpers ────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; RED=$'\033[0;31m'; BLUE=$'\033[0;34m'; RESET=$'\033[0m'
else
  GREEN=""; YELLOW=""; RED=""; BLUE=""; RESET=""
fi
ok()   { echo "${GREEN}✓${RESET} $*"; }
warn() { echo "${YELLOW}!${RESET} $*"; }
err()  { echo "${RED}✗${RESET} $*" >&2; }
say()  { echo "${BLUE}>${RESET} $*"; }

command -v gh >/dev/null 2>&1 || { err "gh CLI not on PATH"; exit 1; }

# URL-encode the package name (the slash in 'ai-o11y-demo-apps/foo' must become %2F)
urlencode() { python3 -c "import urllib.parse, sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$1"; }

for pkg in "${PACKAGES[@]}"; do
  encoded="$(urlencode "$pkg")"
  say "Setting ${pkg} public..."
  if gh api -X PATCH \
       -H "Accept: application/vnd.github+json" \
       "/users/${OWNER}/packages/container/${encoded}" \
       -f visibility=public >/dev/null 2>&1; then
    ok "${pkg} is now public"
  else
    # Check if it just doesn't exist yet (CI hasn't built it)
    if ! gh api "/users/${OWNER}/packages/container/${encoded}" >/dev/null 2>&1; then
      warn "${pkg} doesn't exist on GHCR yet — run after CI completes"
    else
      err "${pkg} — failed to flip visibility (may already be public)"
    fi
  fi
done

echo
ok "Done. Re-run after future CI cycles if you add a new component."
