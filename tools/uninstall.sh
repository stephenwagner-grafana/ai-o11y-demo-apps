#!/usr/bin/env bash
# uninstall.sh — tear down ai-o11y-demo-apps from the current Kubernetes context.
#
# What this script does:
#   1. helm uninstall ai-o11y-demo-apps  (deletes all Deployments / Services /
#      Secrets / ConfigMaps / the Postgres StatefulSet)
#   2. Optionally deletes the Postgres PVC + the 5 namespaces (with confirmation)
#   3. Reports what's left
#
# Inverse of tools/install.sh. Safe to re-run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

RELEASE="ai-o11y-demo-apps"
NAMESPACES=(k6-loadgen neoncart support-bot ai-o11y-postgres llm-gateway)

# ── output helpers ────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; BLUE=$'\033[0;34m'; RESET=$'\033[0m'
else
  RED=""; GREEN=""; YELLOW=""; BLUE=""; RESET=""
fi
say()  { echo "${BLUE}>${RESET} $*"; }
ok()   { echo "${GREEN}✓${RESET} $*"; }
warn() { echo "${YELLOW}!${RESET} $*"; }
err()  { echo "${RED}✗${RESET} $*" >&2; }
die()  { err "$*"; exit 1; }
hdr()  { echo; echo "${BLUE}━━━ $* ━━━${RESET}"; }
ask_yn() {
  local prompt="$1" default="${2:-N}"
  local hint
  [[ "$default" == "Y" ]] && hint="[Y/n]" || hint="[y/N]"
  read -r -p "${prompt} ${hint} " ans
  ans="${ans:-$default}"
  [[ "$ans" =~ ^[Yy]$ ]]
}

# ── prereqs ───────────────────────────────────────────────────────────────────
check_prereqs() {
  hdr "Prereqs"
  command -v kubectl >/dev/null 2>&1 || die "kubectl not on PATH"
  command -v helm    >/dev/null 2>&1 || die "helm not on PATH"
  if ! kubectl cluster-info >/dev/null 2>&1; then
    die "kubectl can't reach the cluster (check your context: kubectl config current-context)"
  fi
  # current-context may be empty (direct kubeconfig / in-cluster SA);
  # cluster-info already proved we can reach the API.
  local ctx
  ctx=$(kubectl config current-context 2>/dev/null || echo "<unset, using direct kubeconfig>")
  ok "Tools OK. Current context: ${ctx}"
}

# ── helm uninstall ────────────────────────────────────────────────────────────
# The release can be installed into ANY namespace (helm defaults to whatever
# the kubeconfig's current namespace is). `helm status` and `helm uninstall`
# without -n only check the default namespace, so we discover the namespace
# the release is actually in via `helm list -A`.
helm_uninstall() {
  hdr "Helm uninstall"
  local rel_ns
  rel_ns=$(helm list -A -f "^${RELEASE}$" -o json 2>/dev/null \
    | grep -oE '"namespace":"[^"]+"' \
    | head -n1 \
    | sed 's/"namespace":"\([^"]*\)"/\1/')
  if [[ -z "${rel_ns}" ]]; then
    warn "Helm release '${RELEASE}' not found in any namespace — nothing to uninstall."
    return 0
  fi
  say "Found release '${RELEASE}' in namespace '${rel_ns}'"
  helm uninstall "${RELEASE}" -n "${rel_ns}"
  ok "Helm release deleted"
}

# ── PVC cleanup (Postgres data) ───────────────────────────────────────────────
delete_pvcs() {
  hdr "Postgres PVC"
  local found
  found="$(kubectl -n ai-o11y-postgres get pvc -o name 2>/dev/null || true)"
  if [[ -z "${found}" ]]; then
    warn "No PVCs found in ai-o11y-postgres."
    return 0
  fi
  echo "Found these PVCs:"
  echo "${found}" | sed 's/^/    /'
  if ask_yn "Delete them? (deletes seeded catalog data permanently)" "N"; then
    echo "${found}" | xargs -r kubectl -n ai-o11y-postgres delete
    ok "PVCs deleted"
  else
    say "Skipped — re-running install will reuse the existing data."
  fi
}

# ── namespace cleanup ─────────────────────────────────────────────────────────
delete_namespaces() {
  hdr "Namespaces"
  local existing=()
  for ns in "${NAMESPACES[@]}"; do
    if kubectl get ns "$ns" >/dev/null 2>&1; then
      existing+=("$ns")
    fi
  done
  if [[ ${#existing[@]} -eq 0 ]]; then
    warn "No demo namespaces found."
    return 0
  fi
  echo "Found these namespaces:"
  printf "    %s\n" "${existing[@]}"
  if ask_yn "Delete them?" "N"; then
    kubectl delete ns "${existing[@]}"
    ok "Namespaces deleted"
  else
    say "Skipped — namespaces will linger but should be empty."
  fi
}

# ── local artifact cleanup ────────────────────────────────────────────────────
cleanup_local() {
  hdr "Local artifacts"
  local files=(
    "${REPO_ROOT}/.helm-values-overrides.yaml"
    "${REPO_ROOT}/helm/config/users.yaml"
  )
  local existing=()
  for f in "${files[@]}"; do
    [[ -f "$f" ]] && existing+=("$f")
  done
  if [[ ${#existing[@]} -eq 0 ]]; then
    warn "No local generated artifacts to delete."
    return 0
  fi
  echo "Would delete:"
  printf "    %s\n" "${existing[@]}"
  if ask_yn "Delete them?" "N"; then
    rm -f "${existing[@]}"
    ok "Local artifacts cleaned"
  else
    say "Skipped — re-run install.sh to regenerate."
  fi
  warn ".env preserved on purpose — delete it manually if you want a fresh wizard run."
}

# ── status ────────────────────────────────────────────────────────────────────
print_status() {
  hdr "Status"
  if helm status "${RELEASE}" >/dev/null 2>&1; then
    err "Release ${RELEASE} STILL EXISTS — check helm status ${RELEASE}"
  else
    ok "Helm release gone"
  fi
  for ns in "${NAMESPACES[@]}"; do
    if kubectl get ns "$ns" >/dev/null 2>&1; then
      warn "namespace ${ns} still exists"
    fi
  done
}

# ── main ──────────────────────────────────────────────────────────────────────
main() {
  hdr "ai-o11y-demo-apps uninstall"
  say "Repo root: ${REPO_ROOT}"

  check_prereqs
  helm_uninstall
  delete_pvcs
  delete_namespaces
  cleanup_local
  print_status

  hdr "Done"
}

main "$@"
