#!/usr/bin/env bash
# Post-install sanity check for ai-o11y-demo-apps.
#
# Exits 0 on success, non-zero on first failure.
# Prints a one-line check/cross per check.
set -euo pipefail

# ── Pretty output (no emojis — greppable + portable) ─────────────────────────
pass() { printf '  [PASS] %s\n' "$*"; }
fail() { printf '  [FAIL] %s\n' "$*" >&2; exit 1; }
info() { printf '  [...]  %s\n' "$*"; }
hdr()  { printf '\n=== %s ===\n' "$*"; }

NAMESPACES=(
  "neoncart"
  "support-bot"
  "llm-gateway"
  "ai-o11y-postgres"
  "k6-loadgen"
)

# ── 1. Prereqs ────────────────────────────────────────────────────────────────
check_kubectl() {
  hdr "Checking kubectl"
  command -v kubectl >/dev/null 2>&1 || fail "kubectl not found on PATH"
  kubectl cluster-info >/dev/null 2>&1 || fail "kubectl can't reach a cluster"
  pass "kubectl reaches cluster: $(kubectl config current-context)"
}

# ── 2. All pods Running in expected namespaces ───────────────────────────────
check_pods_running() {
  hdr "Pod health by namespace"
  for ns in "${NAMESPACES[@]}"; do
    # Must exist
    if ! kubectl get ns "$ns" >/dev/null 2>&1; then
      fail "Namespace ${ns} not found"
    fi

    # Count pods and how many are Running
    local total running
    total=$(kubectl get pods -n "$ns" --no-headers 2>/dev/null | wc -l | tr -d ' ')
    if [[ "$total" -eq 0 ]]; then
      fail "Namespace ${ns}: no pods present"
    fi
    # Treat both "Running" + "Completed" as healthy (Completed = one-shot job)
    running=$(kubectl get pods -n "$ns" --no-headers 2>/dev/null \
              | awk '$3 == "Running" || $3 == "Completed" {n++} END {print n+0}')

    if [[ "$running" -ne "$total" ]]; then
      kubectl get pods -n "$ns" >&2
      fail "Namespace ${ns}: ${running}/${total} pods healthy"
    fi
    pass "Namespace ${ns}: ${running}/${total} pods healthy"
  done
}

# ── 3. Gateway /health and /open ─────────────────────────────────────────────
# Use `kubectl exec` against an existing pod (no debug pod required).
# Pick a pod with curl available — fall back to wget — fall back to python3.
check_gateway_endpoints() {
  hdr "Gateway endpoints"

  # Pick the gateway pod
  local gw_pod
  gw_pod=$(kubectl get pods -n llm-gateway -l app=llm-gateway -o name 2>/dev/null | head -n1 || true)
  if [[ -z "$gw_pod" ]]; then
    # Fall back: pick any pod in the namespace (in case the label isn't set yet)
    gw_pod=$(kubectl get pods -n llm-gateway -o name 2>/dev/null | head -n1 || true)
  fi
  [[ -n "$gw_pod" ]] || fail "No gateway pod found in llm-gateway namespace"
  info "Using ${gw_pod}"

  # /health — the gateway exposes :8000 by convention
  local out
  if out=$(kubectl exec -n llm-gateway "$gw_pod" -- \
        sh -c 'wget -qO- http://localhost:8000/health 2>/dev/null || curl -sf http://localhost:8000/health' 2>/dev/null); then
    if [[ "$out" == *'"ok"'* ]]; then
      pass "Gateway /health returned ok"
    else
      fail "Gateway /health unexpected payload: ${out}"
    fi
  else
    fail "Gateway /health request failed"
  fi

  # /open — should JSON-decode and have providers.anthropic
  if out=$(kubectl exec -n llm-gateway "$gw_pod" -- \
        sh -c 'wget -qO- http://localhost:8000/open 2>/dev/null || curl -sf http://localhost:8000/open' 2>/dev/null); then
    if [[ "$out" == *'anthropic'* ]]; then
      pass "Gateway /open returned anthropic state"
    else
      fail "Gateway /open missing 'anthropic' field: ${out}"
    fi
  else
    fail "Gateway /open request failed"
  fi
}

# ── 4. NC end-to-end chat smoke test ─────────────────────────────────────────
# Fire one request at neoncart-web /api/copilot/chat and confirm shape.
check_nc_chat() {
  hdr "NeonCart /api/copilot/chat smoke test"

  local nc_pod
  nc_pod=$(kubectl get pods -n neoncart -l app=neoncart-web -o name 2>/dev/null | head -n1 || true)
  if [[ -z "$nc_pod" ]]; then
    nc_pod=$(kubectl get pods -n neoncart -o name 2>/dev/null | head -n1 || true)
  fi
  [[ -n "$nc_pod" ]] || fail "No neoncart-web pod found"
  info "Using ${nc_pod}"

  # Exec curl/wget from inside the pod against its own port — avoids us needing
  # to know the service port from outside.
  local payload='{"message":"hi"}'
  local out
  if out=$(kubectl exec -n neoncart "$nc_pod" -- sh -c "
        wget -qO- --post-data='${payload}' \
          --header='Content-Type: application/json' \
          http://localhost:8000/api/copilot/chat 2>/dev/null \
        || curl -sf -X POST -H 'Content-Type: application/json' \
          -d '${payload}' http://localhost:8000/api/copilot/chat
      " 2>/dev/null); then
    # Response shape: expect a JSON object with at minimum a "reply" or "content" field.
    if [[ "$out" == *'reply'* || "$out" == *'content'* || "$out" == *'message'* ]]; then
      pass "NC /api/copilot/chat returned a reply-shaped payload"
    else
      fail "NC /api/copilot/chat returned unexpected shape: ${out:0:200}"
    fi
  else
    fail "NC /api/copilot/chat request failed"
  fi
}

# ── 5. Loadgen activity (optional, advisory) ─────────────────────────────────
# This one only warns — fresh installs may not have spawned a VU yet.
check_loadgen_activity() {
  hdr "Loadgen activity (advisory)"

  local lg_pod
  lg_pod=$(kubectl get pods -n k6-loadgen -o name 2>/dev/null | head -n1 || true)
  if [[ -z "$lg_pod" ]]; then
    info "No loadgen pod yet — skipping"
    return 0
  fi
  info "Tailing last 100 lines of ${lg_pod} for VU spawn markers"

  # We don't fail on this — loadgen may still be ramping. Just report.
  local logs
  logs=$(kubectl logs -n k6-loadgen --tail=100 "$lg_pod" 2>/dev/null || true)
  if printf '%s' "$logs" | grep -Eqi 'spawned VU|iteration|http_reqs'; then
    pass "Loadgen has produced VU/traffic markers"
  else
    info "Loadgen running but no VU markers yet — give it a minute"
  fi
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
  hdr "ai-o11y-demo-apps verifier"
  check_kubectl
  check_pods_running
  check_gateway_endpoints
  check_nc_chat
  check_loadgen_activity
  hdr "All checks passed"
}

main "$@"
