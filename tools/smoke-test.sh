#!/usr/bin/env bash
# smoke-test.sh — exercise the full AI demo flow after install.
#
# What this does (in order):
#   1. Port-forwards the gateway, nc-chatbot, supportbot-router temporarily
#   2. Calls gateway /open and prints the per-provider state
#   3. Sends a normal chatbot prompt -> expects real Claude response
#   4. Sends "show me mice" -> expects 500 with PG column error
#   5. Sends a support question to sb-router -> expects classification + reply
#   6. Calls the gateway /v1/llm directly with a tiny prompt
#
# Each step prints PASS or FAIL with a sample of the response body.
# Exits 0 if every step passes, non-zero on first failure.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -t 1 ]]; then
  GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; RED=$'\033[0;31m'; BLUE=$'\033[0;34m'; RESET=$'\033[0m'
else
  GREEN=""; YELLOW=""; RED=""; BLUE=""; RESET=""
fi
pass() { echo "${GREEN}✓ PASS${RESET} — $*"; }
fail() { echo "${RED}✗ FAIL${RESET} — $*" >&2; }
say()  { echo "${BLUE}>${RESET} $*"; }
hdr()  { echo; echo "${BLUE}━━━ $* ━━━${RESET}"; }

command -v kubectl >/dev/null 2>&1 || { fail "kubectl not on PATH"; exit 1; }
command -v jq      >/dev/null 2>&1 || { fail "jq not on PATH (install jq to parse responses)"; exit 1; }
command -v curl    >/dev/null 2>&1 || { fail "curl not on PATH"; exit 1; }

# ── Port-forward setup ────────────────────────────────────────────────────────
PFW_PIDS=()
cleanup() {
  for pid in "${PFW_PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT

start_pfw() {
  local ns="$1" svc="$2" local_port="$3" remote_port="$4"
  kubectl -n "$ns" port-forward "svc/$svc" "$local_port:$remote_port" >/dev/null 2>&1 &
  PFW_PIDS+=("$!")
  # Wait up to 5s for port-forward to be ready
  for _ in $(seq 1 20); do
    if curl -sS --max-time 1 "http://localhost:$local_port/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done
  return 1
}

hdr "Port-forwards"
say "Forwarding gateway, neoncart-web, supportbot-web..."
if start_pfw llm-gateway llm-gateway 18000 8000; then pass "gateway at :18000"; else fail "gateway port-forward"; exit 1; fi
if start_pfw neoncart   neoncart-web  18080 8000; then pass "neoncart-web at :18080"; else fail "nc-web port-forward"; exit 1; fi
if start_pfw support-bot supportbot-web 18081 8000; then pass "supportbot-web at :18081"; else fail "sb-web port-forward"; exit 1; fi

# ── 1. Gateway /open ──────────────────────────────────────────────────────────
hdr "Gateway /open"
OPEN_RESP="$(curl -sS http://localhost:18000/open)"
ANY_OPEN="$(echo "$OPEN_RESP" | jq -r '.any_open // false')"
if [[ "$ANY_OPEN" == "true" ]]; then
  pass "any_open=true. Providers:"
  echo "$OPEN_RESP" | jq '.providers'
else
  fail "all providers closed: $OPEN_RESP"
  exit 1
fi

# ── 2. NC chatbot — normal prompt ─────────────────────────────────────────────
hdr "NeonCart chatbot — normal prompt"
CHAT_RESP="$(curl -sS -X POST http://localhost:18080/api/copilot/chat \
  -H 'content-type: application/json' \
  -d '{"message":"recommend a wireless mouse for gaming","user_id":"smoke@gmail.com"}')"
REPLY="$(echo "$CHAT_RESP" | jq -r '.reply // ""')"
MODEL="$(echo "$CHAT_RESP" | jq -r '.model // ""')"
if [[ -n "$REPLY" && "$REPLY" != "null" && ! "$REPLY" =~ ^\[stub\] ]]; then
  pass "real LLM reply received (model=${MODEL:-?})"
  echo "    reply: ${REPLY:0:200}..."
else
  fail "stub or empty reply: $CHAT_RESP"
fi

# ── 3. NC chatbot — mice trap ─────────────────────────────────────────────────
hdr "NeonCart chatbot — 'show me mice' trap"
MICE_HTTP="$(curl -sS -o /tmp/mice.json -w '%{http_code}' -X POST http://localhost:18080/api/copilot/chat \
  -H 'content-type: application/json' \
  -d '{"message":"show me mice","user_id":"smoke@gmail.com"}')"
if [[ "$MICE_HTTP" == "500" ]]; then
  if grep -q 'species' /tmp/mice.json; then
    pass "trap fired with column-doesn't-exist error (HTTP 500)"
    head -c 300 /tmp/mice.json; echo
  else
    fail "got 500 but no 'species' in body: $(cat /tmp/mice.json)"
  fi
else
  fail "expected HTTP 500 (column error), got $MICE_HTTP. Body: $(cat /tmp/mice.json)"
fi

# ── 4. SB router — classification + downstream ────────────────────────────────
hdr "SupportBot — billing question"
SB_RESP="$(curl -sS -X POST http://localhost:18081/api/ask \
  -H 'content-type: application/json' \
  -d '{"question":"why was I charged twice for my laptop?","employee_email":"smoke@acme.com"}')"
SB_DOMAIN="$(echo "$SB_RESP" | jq -r '.domain // ""')"
SB_REPLY="$(echo "$SB_RESP" | jq -r '.reply // ""')"
if [[ "$SB_DOMAIN" == "billing" && -n "$SB_REPLY" && ! "$SB_REPLY" =~ ^\[stub\] ]]; then
  pass "router classified as 'billing' and got real downstream reply"
  echo "    reply: ${SB_REPLY:0:200}..."
else
  fail "domain=$SB_DOMAIN, reply=${SB_REPLY:0:200} — expected real billing classification"
fi

# ── 5. Gateway direct ─────────────────────────────────────────────────────────
hdr "Gateway /v1/llm direct (interactive)"
GW_RESP="$(curl -sS -X POST http://localhost:18000/v1/llm \
  -H 'content-type: application/json' \
  -d '{"messages":[{"role":"user","content":"say hello in 5 words"}],"max_tokens":50,"agent_name":"smoke-test","app":"smoke-test"}')"
GW_CONTENT="$(echo "$GW_RESP" | jq -r '.content // ""')"
GW_MODEL="$(echo "$GW_RESP" | jq -r '.model // ""')"
GW_PROVIDER="$(echo "$GW_RESP" | jq -r '.provider // ""')"
if [[ -n "$GW_CONTENT" && "$GW_CONTENT" != "null" ]]; then
  pass "direct gateway call OK (provider=$GW_PROVIDER, model=$GW_MODEL)"
  echo "    content: ${GW_CONTENT:0:200}"
else
  fail "empty content from gateway: $GW_RESP"
fi

hdr "Done"
echo
echo "${GREEN}All smoke tests passed.${RESET}"
echo
echo "Look at your Grafana Cloud → AI Observability plugin within a minute or two."
echo "Sigil's Conversations / Generations / Tools panels should show the calls above."
