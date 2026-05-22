// _common.js — helpers shared across all loadgen K6 scripts.
//
// Loaded by every scenario script. Provides:
//   - loadUsers() — read the JSON pool from $USERS_FILE
//   - syntheticHeaders(userEmail) — the required X-Caller-Type: synthetic
//     header on EVERY request, plus a stable per-session header
//   - sleepStep() / sleepPonder() — humanized delays
//   - pickWeighted(opts) — weighted random pick
//   - randInt(a, b) — uniform int in [a,b] inclusive
//   - shuffle(arr) — Fisher-Yates shuffle (returns a new array)
//   - randSessionId() / randConversationId() — short opaque IDs
//
// IMPORTANT: every HTTP call MUST go through `request(...)` (or use
// `syntheticHeaders` directly) so the gateway sees `X-Caller-Type: synthetic`
// and routes loadgen traffic via its random-across-providers path. Without
// the header the gateway treats the call as interactive and sends it to
// Claude — defeating the entire point of having multiple providers.

import http from 'k6/http';
import { sleep } from 'k6';

// ── Users / cohort ────────────────────────────────────────────────────────────

export function loadUsers() {
  const file = __ENV.USERS_FILE;
  if (!file) {
    throw new Error('USERS_FILE env var not set; orchestrator should provide it');
  }
  // k6's open() reads synchronously at init time. The caller wraps this in
  // open(file) explicitly because k6 only allows open() in the init context.
  return JSON.parse(open(file));
}

// ── HTTP helpers ──────────────────────────────────────────────────────────────

/** Headers that MUST be on every request from this loadgen. */
export function syntheticHeaders(userEmail, sessionId) {
  const h = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    'X-Caller-Type': 'synthetic',     // <-- the critical bit
    'User-Agent': 'ai-o11y-loadgen-k6/0.1',
  };
  if (userEmail) h['X-Synthetic-User'] = userEmail;
  if (sessionId) h['X-Session-Id'] = sessionId;
  return h;
}

/** Wrap http.{get,post,...} with the synthetic headers + a default timeout. */
export function request(method, url, body, user, sessionId, extra) {
  const params = {
    headers: Object.assign({}, syntheticHeaders(user && user.email, sessionId), (extra && extra.headers) || {}),
    timeout: (extra && extra.timeout) || '60s',
    tags: Object.assign({ caller_type: 'synthetic' }, (extra && extra.tags) || {}),
  };
  const payload = body == null ? null : (typeof body === 'string' ? body : JSON.stringify(body));
  switch (method.toUpperCase()) {
    case 'GET': return http.get(url, params);
    case 'POST': return http.post(url, payload, params);
    case 'PUT': return http.put(url, payload, params);
    case 'DELETE': return http.del(url, payload, params);
    default: throw new Error(`unsupported HTTP method ${method}`);
  }
}

// ── Timing helpers ────────────────────────────────────────────────────────────

export function sleepStep() {
  // 3-15 s inter-step delay (uniform), with an occasional 30 s ponder
  if (Math.random() < 0.08) {
    sleep(30 * (0.8 + 0.4 * Math.random()));
  } else {
    sleep(3 + Math.random() * 12);
  }
}

export function sleepPonder() {
  sleep(20 + Math.random() * 15);
}

export function sleepShort() {
  sleep(1 + Math.random() * 2);
}

// ── Randomization helpers ─────────────────────────────────────────────────────

export function randInt(a, b) {
  return Math.floor(a + Math.random() * (b - a + 1));
}

export function shuffle(arr) {
  const out = arr.slice();
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

export function pickWeighted(options) {
  // options: [{value, weight}, ...]
  const total = options.reduce((s, o) => s + o.weight, 0);
  let r = Math.random() * total;
  for (const o of options) {
    r -= o.weight;
    if (r <= 0) return o.value;
  }
  return options[options.length - 1].value;
}

export function pickOne(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

// ── ID helpers ────────────────────────────────────────────────────────────────

export function randHex(len) {
  const chars = '0123456789abcdef';
  let s = '';
  for (let i = 0; i < len; i++) s += chars[Math.floor(Math.random() * 16)];
  return s;
}

export function randSessionId() {
  return `sess_${randHex(16)}`;
}

export function randConversationId() {
  return `conv_${randHex(16)}`;
}

// ── Session arrival pacing ────────────────────────────────────────────────────

/**
 * Compute a per-VU iteration count and base interval. Used by callers that
 * pick a constant-arrival-rate executor; here we expose helpers if scripts
 * want to self-pace inside a single VU instead.
 */
export function nominalSessionsPerHour() {
  const v = parseInt(__ENV.SESSIONS_PER_HOUR || '60', 10);
  return Number.isFinite(v) && v > 0 ? v : 60;
}
