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

// ── prompt pool (30+ prompts) ─────────────────────────────────────────────────
//
// Real gift-finder prompts almost always pack (a) who, (b) occasion, (c) hint
// at interest/budget. We bias the pool toward that shape so Sigil reviewers
// see contextual prompts instead of "gift for a person."

const PROMPTS = [
  // — occasion + relationship + interest —
  "birthday gift for my 12-year-old nephew who loves gaming",
  "anniversary gift for my husband, he's into smart home stuff",
  "graduation gift under $200 for my niece, going to art school",
  "secret santa for office, $25 limit, gender-neutral",
  "wedding present for friends in their 30s, they love cooking",
  "housewarming gift for a couple who just bought a fixer-upper",
  "father's day gift, my dad is a tinkerer who fixes everything",
  "mother's day gift, she loves cooking but already has every gadget",
  "valentine's day gift for my girlfriend, not flowers or chocolate",
  "birthday gift for my dad who recently got into vinyl records",
  "anniversary gift under $100 for my wife, she's an audiophile",
  "retirement gift for my boss, 35 years at the company",
  "baby shower gift, the parents are super into tech",
  "promotion gift for my best friend, just made VP",
  "thank-you gift for the neighbor who watched our dog all week",

  // — specific recipients without a holiday —
  "gift for my mom, she works from home and complains about her back",
  "gift for my brother who works in finance and travels constantly",
  "gift for my college roommate, she just moved to a tiny NYC apartment",
  "gift for my teenage daughter who's obsessed with K-pop and her phone",
  "gift for my grandpa who's 78 and just got his first smart tv",
  "gift for my sister who's a new mom and never sleeps",
  "gift for a friend who just started running marathons",
  "small thoughtful gift for a coworker I barely know but should",
  "gift for my partner, they're into mechanical keyboards",
  "tech gift for someone who hates tech",
  "gift for a friend who just got their first apartment",
  "thank-you gift under $50 for someone who helped me move",

  // — budget-led —
  "stocking stuffer ideas under $40, something they'd actually use",
  "secret santa gift under $30 that doesn't look like secret santa",
  "white elephant gift, $20, funny but actually useful",
  "$500 splurge gift for my husband's 40th birthday",
  "under $75 birthday gift for a 10-year-old who likes Minecraft",
  "gift around $150 for my best friend, she has expensive taste",

  // — hard mode —
  "gift for someone who has literally everything",
  "gift for my mother-in-law and I don't really know her",
  "gift for a long-distance friend, has to ship by friday",
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
  "can you compare those?",
  "show me something that ships fast",
  "anything more giftable — better packaging",
  "what if my budget were a bit higher?",
  "I want something nicer, splurge mode",
];

// ── helpers ───────────────────────────────────────────────────────────────────

function pickUser() {
  // Stable: cohort already filtered by orchestrator; we just pick uniformly.
  return users[Math.floor(Math.random() * users.length)];
}

/**
 * Optionally append a small persona-flavored hint to a gift prompt. AOL/Yahoo
 * cohorts read as older-shoppers and lean toward "for the grandkids" / lower
 * budgets; gmail mostly leaves the prompt untouched. Kept short so we always
 * stay under the 200-char chat budget.
 */
function shapeByPersona(user, prompt) {
  if (!user || !user.email) return prompt;
  if (Math.random() < 0.6) return prompt;
  const email = user.email.toLowerCase();
  let suffix = null;
  if (email.endsWith('@aol.com')) {
    suffix = pickOne([
      ' — keep it simple please',
      ' — something easy to set up',
      ' — under $50 if you can',
    ]);
  } else if (email.endsWith('@yahoo.com')) {
    suffix = pickOne([
      ' — for the grandkids',
      ' — they aren\'t very techy',
      ' — has to be useful, not flashy',
    ]);
  } else if (email.endsWith('@gmail.com')) {
    if (Math.random() < 0.4) {
      suffix = pickOne([
        ' — bonus if it ships prime-fast',
        ' — looks nice unboxed',
        ' — eco-friendly is a plus',
      ]);
    }
  }
  if (!suffix) return prompt;
  const combined = prompt + suffix;
  return combined.length > 200 ? prompt : combined;
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
    const recs = callGiftFinder(user, sessionId, conversationId, shapeByPersona(user, pickOne(PROMPTS)));
    sleepStep();
    browseRecs(user, sessionId, recs);
    // ~30% of even "single-shot" gift-finder sessions follow up with a
    // refinement after seeing the first round — keeps multi-turn density up
    // and avoids the prompt feed looking one-turn-per-session.
    if (Math.random() < 0.3) {
      callGiftFinder(user, sessionId, conversationId, pickOne(REFINEMENTS));
      sleepStep();
    }
  });
}

function journeyRefining(user) {
  group('refining', () => {
    const sessionId = randSessionId();
    const conversationId = randConversationId();
    request('GET', `${BASE}/`, null, user, sessionId);
    sleepStep();
    callGiftFinder(user, sessionId, conversationId, shapeByPersona(user, pickOne(PROMPTS)));
    sleepPonder();
    // Refine using a new prompt within the same conversation_id (sigil sees
    // it as a multi-turn convo). The specialist doesn't have history today,
    // but the conversation_id reuse still gives us proper grouping in Sigil.
    // Half the time it's a straight refinement ("cheaper options"), half it
    // re-anchors with a new full prompt + a clarifier.
    const refined = Math.random() < 0.5
      ? pickOne(REFINEMENTS)
      : `${shapeByPersona(user, pickOne(PROMPTS))} — ${pickOne(REFINEMENTS)}`;
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
    const recs = callGiftFinder(user, sessionId, conversationId, shapeByPersona(user, pickOne(PROMPTS)));
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
    const recs = callGiftFinder(user, sessionId, conversationId, shapeByPersona(user, pickOne(PROMPTS)));
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
