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
//
// Pools are intentionally large (25-40 each) so that a Sigil reviewer scanning
// the prompt feed doesn't see the same 5 sentences over and over. New entries
// should read like quick chat messages a real shopper would type — lowercase,
// short, occasional typos and casual phrasing are fine.

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
  "do you offer financing on big-ticket items?",
  "is there a student discount?",
  "do gift cards expire?",
  "can I exchange a gift without a receipt?",
  "where's my refund? you said 5-7 days",
  "do you have black friday deals coming up?",
  "is two-day shipping really two days?",
  "can I add insurance to my package?",
  "do you have signature-required delivery?",
  "what's the difference between your standard and premium support?",
  "can I subscribe & save on accessories?",
  "what does the holiday return window look like?",
  "are open-box items still under warranty?",
  "do you take old electronics for trade-in?",
  "can I pick up an order in store?",
  "are your batteries OEM or aftermarket?",
  "what happens if my package gets stolen off my porch?",
  "is it cheaper to buy a bundle or each piece separately?",
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
  "do you have wireless earbuds under $100?",
  "what's the difference between mechanical and membrane keyboards?",
  "I need a monitor for video editing, color-accurate",
  "show me something with rgb",
  "I'm looking for a gift for my dad who likes podcasts",
  "best mouse for someone with big hands?",
  "what mics do streamers use?",
  "I want a thunderbolt 4 dock that runs cool",
  "anything cheap that works with sonos?",
  "ultrawide monitor recommendations under $600",
  "I need a webcam that doesn't suck in low light",
  "what tablet do you recommend for note-taking?",
  "looking for an all-in-one printer that does duplex",
  "show me ssds — fastest under $150",
  "any quiet mechanical switches you carry?",
  "what's a good gaming headset that won't crush my glasses?",
  "I want a vertical mouse to help my wrist",
  "show me your most-reviewed standing desk",
  "show me a router that handles 50+ devices",
  "what's the best budget e-reader you have?",
];

const MULTI_TURN_OPENERS = [
  "I'm looking for a gift",
  "I need a new keyboard",
  "what's the best monitor for me?",
  "help me pick headphones",
  "I want a webcam for streaming",
  "I need a laptop bag that fits a 16-inch macbook",
  "help me set up a home office",
  "I'm building my first gaming pc",
  "I need a new desk chair, my back is killing me",
  "looking to upgrade my whole audio setup",
  "I want to start podcasting from my apartment",
  "I need a second monitor for working from home",
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
  "can you compare those?",
  "show me cheaper options",
  "what about something more powerful?",
  "any that ship by friday?",
  "must be quiet — I have meetings all day",
  "do any of them come in white?",
  "which one has the best warranty?",
  "I have a mac, will those still work?",
  "what's the most popular one of those?",
];

const FRUSTRATED_FOLLOWUPS = [
  "that's not what I asked",
  "you're not helpful",
  "let me try again",
  "I'll just look myself",
  "never mind",
  "no I said wireless, not wired",
  "you keep recommending stuff outside my budget",
  "I literally just said no apple",
  "can you just give me a straight answer?",
];

const GIFT_PROMPTS = [
  "birthday gift for my dad",
  "gift for a teenager who likes gaming",
  "anniversary present under $100",
  "graduation gift",
  "secret santa for the office, $25 limit",
  "thank-you gift for my neighbor",
  "thoughtful gift for my sister who just had a baby",
];

// Stock follow-ups used by the ~30% quick-QA + nav-driven sessions that
// continue talking instead of bouncing. Kept generic so any opener flows
// naturally into them.
const STOCK_FOLLOWUPS = [
  "can you compare those?",
  "show me cheaper options",
  "what about something more powerful?",
  "any that have better reviews?",
  "which one ships fastest?",
  "do you have any in stock at my store?",
  "tell me more about the first one",
  "what color options does it come in?",
  "is there a newer model?",
  "what's the return window on that?",
];

// ── helpers ───────────────────────────────────────────────────────────────────

function pickUser() {
  return users[Math.floor(Math.random() * users.length)];
}

/**
 * Lightly shape a base prompt by persona. We don't rewrite the prompt — just
 * occasionally suffix a small persona-flavored hint. This keeps the prompt
 * pool from feeling like a fixed list of 30 strings while staying under the
 * 200-char budget.
 *
 * Heuristic: @aol.com / @yahoo.com lean older-shopper ("for my husband",
 * "for the grandkids", price-sensitive); @gmail.com leans mainstream and we
 * usually leave the prompt untouched.
 */
function shapeByPersona(user, prompt) {
  if (!user || !user.email) return prompt;
  if (Math.random() < 0.55) return prompt; // most of the time, leave it alone
  const email = user.email.toLowerCase();
  let suffix = null;
  if (email.endsWith('@aol.com')) {
    suffix = pickOne([
      ' — easy to use please',
      ' — something my husband would like',
      " — nothing too complicated",
      ' — keep it under $75 if you can',
    ]);
  } else if (email.endsWith('@yahoo.com')) {
    suffix = pickOne([
      ' — for the grandkids',
      ' — has to be reliable',
      ' — no subscription stuff',
    ]);
  } else if (email.endsWith('@gmail.com')) {
    // mainstream — only a small flavor sometimes
    if (Math.random() < 0.4) {
      suffix = pickOne([
        ' (work from home)',
        ' — bonus if it pairs with my phone',
        ' — open to refurb',
      ]);
    }
  }
  if (!suffix) return prompt;
  const combined = prompt + suffix;
  // Stay under the 200-char chat budget.
  return combined.length > 200 ? prompt : combined;
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
    const body = r && r.json && r.json();
    // /api/products returns {"products":[...]} — NOT a bare array. Previously
    // we accessed body.length directly which is always undefined for objects,
    // so the ATC was silently skipped on every call. That kept the
    // neoncart_ai_attributed_revenue_usd_total counter from ever firing and
    // the ROI dashboard panels stayed empty. Pull body.products.
    const list = body && (Array.isArray(body) ? body : body.products);
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
    const opener = shapeByPersona(user, pickOne(QUICK_QUESTIONS));
    callChatbot(user, sessionId, conversationId, opener);
    sleepStep();
    // ~30% of "quick" sessions aren't actually one-and-done: the user reads
    // the answer and follows up with a clarifying question in the same
    // conversation. This produces real multi-turn transcripts in Sigil.
    if (Math.random() < 0.3) {
      callChatbot(user, sessionId, conversationId, pickOne(STOCK_FOLLOWUPS));
      sleepStep();
    }
  });
}

function journeyNavigationDriven(user) {
  group('navigation-driven', () => {
    const sessionId = randSessionId();
    const conversationId = randConversationId();
    request('GET', `${BASE}/`, null, user, sessionId);
    sleepStep();
    // ~1.5% of these flips to "show me mice" — the canonical demo prompt.
    const msg = Math.random() < 0.015
      ? mouseTrapMessage()
      : shapeByPersona(user, pickOne(NAV_QUESTIONS));
    callChatbot(user, sessionId, conversationId, msg);
    sleepStep();
    // ~30% of nav sessions keep talking — "show me cheaper", "compare", etc.
    if (Math.random() < 0.3) {
      callChatbot(user, sessionId, conversationId, pickOne(STOCK_FOLLOWUPS));
      sleepStep();
    }
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
    callChatbot(user, sessionId, conversationId, shapeByPersona(user, pickOne(MULTI_TURN_OPENERS)));
    sleepStep();
    // Mix clarifications with stock follow-ups so multi-turn doesn't read like
    // a templated form ("under $200" → "for office use" → "for gaming"...).
    for (let i = 1; i < turns; i++) {
      const pool = Math.random() < 0.65 ? MULTI_TURN_CLARIFICATIONS : STOCK_FOLLOWUPS;
      callChatbot(user, sessionId, conversationId, pickOne(pool));
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
