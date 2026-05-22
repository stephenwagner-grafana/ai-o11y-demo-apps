// neoncart-gift-finder.js
//
// K6 scenario for the 30 gift-finder-only NeonCart users (a stable cohort —
// these users NEVER use the chatbot, only the gift-finder).
//
// Journey weights (from docs/LOADGEN.md):
//   50% single-shot   — open finder, 1 prompt, browse 3 recs, leave
//   25% refining      — open finder, 1 prompt, unsatisfied, refine, browse, leave
//   20% converting    — open finder, prompt, browse recs, add to cart, checkout
//    5% browse-and-go — open finder, prompt, look, leave without action
//
// Every request carries the X-Caller-Type: synthetic header (set by
// _common.js → syntheticHeaders). The gateway needs this to route loadgen
// traffic away from the always-Claude interactive path; without it the
// gateway treats the call as interactive and ignores /open.

import { check, group, sleep } from 'k6';
import {
  request, sleepStep, sleepPonder, pickWeighted, pickOne, randInt, shuffle,
  randSessionId, randConversationId, loadUsers, nominalSessionsPerHour,
} from './_common.js';

// ── init context ──────────────────────────────────────────────────────────────

const users = loadUsers();
const BASE = __ENV.NC_BASE_URL || 'http://nc-web.neoncart.svc.cluster.local';

// ── k6 options ────────────────────────────────────────────────────────────────

const sph = nominalSessionsPerHour();
const ratePerSecond = Math.max(sph / 3600, 0.001);
export const options = {
  scenarios: {
    nc_gift_finder: {
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

// ── prompt pool (~20 prompts) ─────────────────────────────────────────────────

const PROMPTS = [
  "birthday gift for my dad",
  "anniversary present under $100",
  "gift for a teenager who likes gaming",
  "graduation gift for someone going into engineering",
  "small thoughtful gift for a coworker",
  "wedding present for friends, budget $200",
  "gift for my wife, she likes audio gear",
  "gift for mom, she works from home a lot",
  "housewarming gift for a couple in their 30s",
  "birthday gift for my nephew, he likes PC gaming",
  "father's day gift, my dad is a tinkerer",
  "mother's day gift, she loves cooking",
  "stocking stuffer ideas under $40",
  "secret santa gift under $30",
  "gift for a friend who just got their first apartment",
  "thank you gift for someone who helped me move",
  "tech gift for someone who doesn't like tech",
  "graduation gift for a high schooler heading to college",
  "valentine's day gift, not flowers",
  "gift for my brother who works in finance",
];

// Some "refinement" follow-up prompts for the refining journey
const REFINEMENTS = [
  "cheaper options",
  "something more unique",
  "something under $50",
  "not headphones, something else",
  "more practical, less flashy",
  "something they could use every day",
  "a gift that feels personal",
  "less generic — they have everything",
];

// ── helpers ───────────────────────────────────────────────────────────────────

function pickUser() {
  // Stable: cohort already filtered by orchestrator; we just pick uniformly.
  return users[Math.floor(Math.random() * users.length)];
}

function callGiftFinder(user, sessionId, conversationId, prompt) {
  // The frontend hits the specialist via /api/ai/gift-finder on nc-web.
  // nc-web proxies to nc-gift-finder, which calls llm-gateway.
  const url = `${BASE}/api/ai/gift-finder`;
  const body = {
    prompt,
    session_id: sessionId,
    conversation_id: conversationId,
    user_id: user.email,
    // Hint to nc-gift-finder which gateway agent_name to attribute the call to
    agent_name: 'nc-gift-finder',
  };
  const r = request('POST', url, body, user, sessionId, { timeout: '90s' });
  check(r, {
    'gift-finder 2xx': (res) => res.status >= 200 && res.status < 300,
  });
  let recs = [];
  try {
    const j = r.json();
    recs = (j && (j.recommendations || j.output)) || [];
    if (!Array.isArray(recs)) recs = [];
  } catch (_) { /* leave empty */ }
  return recs;
}

function viewProduct(user, sessionId, sku) {
  return request('GET', `${BASE}/api/products/${encodeURIComponent(sku)}`, null, user, sessionId);
}

function addToCart(user, sessionId, sku) {
  return request('POST', `${BASE}/api/cart/add`, {
    sku, quantity: 1, source: 'ai_gift_finder',
  }, user, sessionId);
}

function checkout(user, sessionId, items) {
  return request('POST', `${BASE}/api/orders`, { items }, user, sessionId);
}

function browseRecs(user, sessionId, recs) {
  // View up to 3 of the recommendations as separate product page hits.
  const subset = shuffle(recs).slice(0, Math.min(3, recs.length));
  for (const rec of subset) {
    const sku = rec && (rec.sku || rec.id);
    if (sku) viewProduct(user, sessionId, sku);
    sleepStep();
  }
  return subset;
}

// ── journeys ──────────────────────────────────────────────────────────────────

function journeySingleShot(user) {
  group('single-shot', () => {
    const sessionId = randSessionId();
    const conversationId = randConversationId();
    request('GET', `${BASE}/`, null, user, sessionId);
    sleepStep();
    const recs = callGiftFinder(user, sessionId, conversationId, pickOne(PROMPTS));
    sleepStep();
    browseRecs(user, sessionId, recs);
  });
}

function journeyRefining(user) {
  group('refining', () => {
    const sessionId = randSessionId();
    const conversationId = randConversationId();
    request('GET', `${BASE}/`, null, user, sessionId);
    sleepStep();
    callGiftFinder(user, sessionId, conversationId, pickOne(PROMPTS));
    sleepPonder();
    // Refine using a new prompt within the same conversation_id (sigil sees
    // it as a multi-turn convo). The specialist doesn't have history today,
    // but the conversation_id reuse still gives us proper grouping in Sigil.
    const refined = `${pickOne(PROMPTS)} — ${pickOne(REFINEMENTS)}`;
    const recs2 = callGiftFinder(user, sessionId, conversationId, refined);
    sleepStep();
    browseRecs(user, sessionId, recs2);
  });
}

function journeyConverting(user) {
  group('converting', () => {
    const sessionId = randSessionId();
    const conversationId = randConversationId();
    request('GET', `${BASE}/`, null, user, sessionId);
    sleepStep();
    const recs = callGiftFinder(user, sessionId, conversationId, pickOne(PROMPTS));
    sleepStep();
    const viewed = browseRecs(user, sessionId, recs);
    if (viewed.length > 0) {
      const sku = viewed[0].sku || viewed[0].id;
      if (sku) {
        addToCart(user, sessionId, sku);
        sleepPonder();
        checkout(user, sessionId, [{ sku, quantity: 1 }]);
      }
    }
  });
}

function journeyBrowseAndGo(user) {
  group('browse-and-go', () => {
    const sessionId = randSessionId();
    const conversationId = randConversationId();
    request('GET', `${BASE}/`, null, user, sessionId);
    sleepStep();
    const recs = callGiftFinder(user, sessionId, conversationId, pickOne(PROMPTS));
    sleepStep();
    if (recs.length > 0) {
      const sku = recs[0].sku || recs[0].id;
      if (sku) viewProduct(user, sessionId, sku);
    }
    // No add, no checkout. User leaves.
  });
}

// ── entrypoint ────────────────────────────────────────────────────────────────

export function session() {
  if (users.length === 0) {
    sleep(60);
    return;
  }
  const user = pickUser();
  const journey = pickWeighted([
    { value: 'single', weight: 50 },
    { value: 'refine', weight: 25 },
    { value: 'convert', weight: 20 },
    { value: 'browse', weight: 5 },
  ]);
  switch (journey) {
    case 'single':  journeySingleShot(user); break;
    case 'refine':  journeyRefining(user); break;
    case 'convert': journeyConverting(user); break;
    case 'browse':  journeyBrowseAndGo(user); break;
  }
}
