// neoncart-chatbot.js
//
// K6 scenario for the 15 chatbot-only NeonCart users (a stable cohort —
// never uses the gift-finder).
//
// Also drives the "both" cohort — when run with users that have the both
// cohort, this script alternates between chatbot and gift-finder per
// iteration so both features get exercised. The orchestrator points the
// "both" scenario at this script (see orchestrator/main.py).
//
// Journey weights (from docs/LOADGEN.md):
//   40% Quick Q&A         — open chatbot, 1 question, read, close
//   35% navigation-driven — open chatbot, "show me X", browse, maybe buy
//   20% multi-turn        — 3-5 turns of clarification, maybe buy
//    5% frustrated        — ask, unsatisfied, re-ask differently, still unsatisfied, leave
//
// "Show me mice" trap: ~1.5% of iterations send the exact message
// "show me mice" to fire the intentional Postgres trap baked into
// nc-chatbot. Keeps that signature trace populated continuously.
//
// Every request carries X-Caller-Type: synthetic (set in _common.js).

import { check, group, sleep } from 'k6';
import {
  request, sleepStep, sleepPonder, pickWeighted, pickOne, randInt,
  randSessionId, randConversationId, loadUsers, nominalSessionsPerHour,
} from './_common.js';

// ── init context ──────────────────────────────────────────────────────────────

const users = loadUsers();
const BASE = __ENV.NC_BASE_URL || 'http://nc-web.neoncart.svc.cluster.local';
const SCENARIO_NAME = __ENV.SCENARIO_NAME || 'neoncart-chatbot';
// Whether to also exercise gift-finder in this VU (the "both" cohort).
const ALSO_GIFT_FINDER = SCENARIO_NAME === 'neoncart-both';

// ── k6 options ────────────────────────────────────────────────────────────────

const sph = nominalSessionsPerHour();
const ratePerSecond = Math.max(sph / 3600, 0.001);
export const options = {
  scenarios: {
    nc_chatbot: {
      executor: 'constant-arrival-rate',
      rate: Math.max(1, Math.round(ratePerSecond * 60)),
      timeUnit: '1m',
      duration: '24h',
      preAllocatedVUs: Math.max(2, Math.ceil(ratePerSecond * 30)),
      maxVUs: Math.max(10, Math.ceil(ratePerSecond * 120)),
      exec: 'session',
    },
  },
};

// ── question pools ────────────────────────────────────────────────────────────

const QUICK_QUESTIONS = [
  "what's your return policy?",
  "how long does shipping take?",
  "do you ship internationally?",
  "what payment methods do you accept?",
  "is this item in stock?",
  "can I cancel my order?",
  "do you price match?",
  "what is your warranty?",
  "do you have a physical store?",
  "how do I track my order?",
];

const NAV_QUESTIONS = [
  "show me running shoes",
  "show me wireless headphones",
  "show me gaming keyboards",
  "show me 4k monitors",
  "show me ergonomic chairs",
  "show me usb-c hubs",
  "show me webcams",
  "show me standing desks",
  "show me bluetooth speakers",
  "show me smart bulbs",
];

const MULTI_TURN_OPENERS = [
  "I'm looking for a gift",
  "I need a new keyboard",
  "what's the best monitor for me?",
  "help me pick headphones",
  "I want a webcam for streaming",
];

const MULTI_TURN_CLARIFICATIONS = [
  "under $200",
  "for office use",
  "for gaming",
  "noise cancelling preferred",
  "USB-C if possible",
  "wireless only",
  "I'd like good battery life",
  "I work from home",
  "I have a small desk",
];

const FRUSTRATED_FOLLOWUPS = [
  "that's not what I asked",
  "you're not helpful",
  "let me try again",
  "I'll just look myself",
  "never mind",
];

const GIFT_PROMPTS = [
  "birthday gift for my dad",
  "gift for a teenager who likes gaming",
  "anniversary present under $100",
  "graduation gift",
];

// ── helpers ───────────────────────────────────────────────────────────────────

function pickUser() {
  return users[Math.floor(Math.random() * users.length)];
}

function callChatbot(user, sessionId, conversationId, message) {
  // The frontend hits the chatbot via /api/copilot/chat on nc-web.
  // nc-web proxies to nc-chatbot, which calls llm-gateway.
  const url = `${BASE}/api/copilot/chat`;
  const body = {
    message,
    session_id: sessionId,
    conversation_id: conversationId,
    user_id: user.email,
    agent_name: 'nc-chatbot',
  };
  const r = request('POST', url, body, user, sessionId, { timeout: '90s' });
  // 500s from the "show me mice" trap are EXPECTED — don't fail the check
  // on them; they're the demo's point.
  check(r, {
    'chatbot responded': (res) => res.status >= 200 && res.status < 600,
  });
  return r;
}

function callGiftFinder(user, sessionId, conversationId, prompt) {
  const url = `${BASE}/api/ai/gift-finder`;
  const body = {
    prompt,
    session_id: sessionId,
    conversation_id: conversationId,
    user_id: user.email,
    agent_name: 'nc-gift-finder',
  };
  return request('POST', url, body, user, sessionId, { timeout: '90s' });
}

function maybeAddAndCheckout(user, sessionId, source) {
  // After a chatbot suggestion, sometimes user adds to cart + checks out.
  // We fetch a real SKU from /api/products since the chatbot reply text
  // doesn't structurally include one; falling back to nothing if the catalog
  // is empty (avoids FK violations against the products table).
  const r = request('GET', `${BASE}/api/products`, null, user, sessionId);
  let sku = null;
  try {
    const list = r && r.json && r.json();
    if (list && list.length > 0) {
      const p = list[Math.floor(Math.random() * list.length)];
      sku = p && (p.sku || p.id);
    }
  } catch (_) { /* swallow parse errors */ }
  if (!sku) return;
  request('POST', `${BASE}/api/cart/add`, {
    sku, quantity: 1, source: source || 'ai_chatbot',
  }, user, sessionId);
  sleepPonder();
  request('POST', `${BASE}/api/orders`, {
    items: [{ sku, quantity: 1 }],
  }, user, sessionId);
}

function mouseTrapMessage() {
  // The trap fires on the substring "mice" (case-insensitive). We use the
  // canonical demo prompt verbatim so transcripts read naturally.
  return "show me mice";
}

// ── journeys ──────────────────────────────────────────────────────────────────

function journeyQuickQA(user) {
  group('quick-qa', () => {
    const sessionId = randSessionId();
    const conversationId = randConversationId();
    request('GET', `${BASE}/`, null, user, sessionId);
    sleepStep();
    callChatbot(user, sessionId, conversationId, pickOne(QUICK_QUESTIONS));
    sleepStep();
  });
}

function journeyNavigationDriven(user) {
  group('navigation-driven', () => {
    const sessionId = randSessionId();
    const conversationId = randConversationId();
    request('GET', `${BASE}/`, null, user, sessionId);
    sleepStep();
    // ~1.5% of these flips to "show me mice" — the canonical demo prompt.
    const msg = Math.random() < 0.015 ? mouseTrapMessage() : pickOne(NAV_QUESTIONS);
    callChatbot(user, sessionId, conversationId, msg);
    sleepStep();
    // Pretend we click the suggested product
    request('GET', `${BASE}/api/products`, null, user, sessionId);
    sleepStep();
    if (Math.random() < 0.35) {
      maybeAddAndCheckout(user, sessionId);
    }
  });
}

function journeyMultiTurn(user) {
  group('multi-turn', () => {
    const sessionId = randSessionId();
    const conversationId = randConversationId();
    request('GET', `${BASE}/`, null, user, sessionId);
    sleepStep();
    const turns = randInt(3, 5);
    callChatbot(user, sessionId, conversationId, pickOne(MULTI_TURN_OPENERS));
    sleepStep();
    for (let i = 1; i < turns; i++) {
      callChatbot(user, sessionId, conversationId, pickOne(MULTI_TURN_CLARIFICATIONS));
      sleepStep();
    }
    if (Math.random() < 0.4) {
      maybeAddAndCheckout(user, sessionId);
    }
  });
}

function journeyFrustrated(user) {
  group('frustrated', () => {
    const sessionId = randSessionId();
    const conversationId = randConversationId();
    request('GET', `${BASE}/`, null, user, sessionId);
    sleepStep();
    callChatbot(user, sessionId, conversationId, pickOne(NAV_QUESTIONS));
    sleepStep();
    callChatbot(user, sessionId, conversationId, pickOne(FRUSTRATED_FOLLOWUPS));
    sleepStep();
    callChatbot(user, sessionId, conversationId, `${pickOne(NAV_QUESTIONS)} please`);
    sleepStep();
  });
}

function bothCohortExtra(user) {
  // "Both" users also exercise the gift-finder. Half the iterations include
  // a gift-finder call in the same session as the chatbot interaction.
  if (!ALSO_GIFT_FINDER) return;
  if (Math.random() < 0.5) return;
  const sessionId = randSessionId();
  const conversationId = randConversationId();
  callGiftFinder(user, sessionId, conversationId, pickOne(GIFT_PROMPTS));
  sleepStep();
}

// ── entrypoint ────────────────────────────────────────────────────────────────

export function session() {
  if (users.length === 0) {
    sleep(60);
    return;
  }
  const user = pickUser();
  const journey = pickWeighted([
    { value: 'quick',      weight: 40 },
    { value: 'navigation', weight: 35 },
    { value: 'multiturn',  weight: 20 },
    { value: 'frustrated', weight: 5 },
  ]);
  switch (journey) {
    case 'quick':      journeyQuickQA(user); break;
    case 'navigation': journeyNavigationDriven(user); break;
    case 'multiturn':  journeyMultiTurn(user); break;
    case 'frustrated': journeyFrustrated(user); break;
  }
  bothCohortExtra(user);
}
