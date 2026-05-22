// supportbot.js
//
// K6 scenario for the ~30 SupportBot ("Ask Acme") users. 100% AI — every
// session sends a question to /api/ask which proxies through sb-router to
// a domain specialist (sb-billing / sb-tech-support / sb-account-management)
// or returns "can't route" for off-topic.
//
// Journey weights (from docs/LOADGEN.md):
//   30% billing question     — single Q&A
//   25% tech-support easy    — single Q&A
//   15% tech-support multi   — 3-5 turn clarification chain
//   20% account question     — single Q&A
//    5% wrong-domain         — off-topic, router replies "can't help"
//    5% frustrated           — Q → unsatisfied → re-ask → re-ask → leave
//
// Every request carries X-Caller-Type: synthetic (set in _common.js). This
// flag tells the gateway "this is loadgen", which is necessary for the
// gateway's multi-provider routing and /open enforcement.

import { check, group, sleep } from 'k6';
import {
  request, sleepStep, sleepPonder, pickWeighted, pickOne, randInt,
  randSessionId, randConversationId, loadUsers, nominalSessionsPerHour,
} from './_common.js';

// ── init context ──────────────────────────────────────────────────────────────

const users = loadUsers();
const BASE = __ENV.SB_BASE_URL || 'http://sb-web.support-bot.svc.cluster.local';

// ── k6 options ────────────────────────────────────────────────────────────────

const sph = nominalSessionsPerHour();
const ratePerSecond = Math.max(sph / 3600, 0.001);
export const options = {
  scenarios: {
    supportbot: {
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

// ── question pools (~15 per domain) ───────────────────────────────────────────

const BILLING_QUESTIONS = [
  "I have a charge I don't recognize on my last invoice",
  "where can I download my receipts?",
  "my payment failed, what do I do?",
  "how do I update my billing email?",
  "I need a refund for last month",
  "why was I charged twice?",
  "can I switch to annual billing?",
  "what payment methods are supported?",
  "my invoice shows a different amount than I expected",
  "how do I add a PO number to invoices?",
  "I want to cancel my subscription",
  "are taxes included on my invoice?",
  "can I get an itemized invoice?",
  "my credit card on file is expired",
  "I was billed during a free trial",
];

const TECH_QUESTIONS = [
  "my laptop won't connect to the office wifi",
  "I'm getting an error when launching the VPN",
  "the app crashes when I open a large file",
  "I can't print to the office printer",
  "my computer is very slow this morning",
  "outlook keeps disconnecting",
  "I need help setting up MFA",
  "the website won't load for me",
  "my microphone isn't working in meetings",
  "the app says my license is invalid",
  "how do I restart the VPN service?",
  "I see a security warning on every page",
  "my screen flickers when I plug in the dock",
  "the file sync isn't working",
  "I can't log into the build server",
];

const ACCOUNT_QUESTIONS = [
  "how do I change my password?",
  "I need to update my email on the account",
  "how do I update my profile picture?",
  "I want to change my display name",
  "how do I request access to the engineering team?",
  "I lost access to my account",
  "can I download my account data?",
  "how do I delete my account?",
  "I need admin permissions for project X",
  "how do I leave an organization?",
  "I see the wrong role on my profile",
  "how do I enable single sign-on?",
  "I need to update my emergency contact",
  "how do I see my login history?",
  "I want to merge two accounts",
];

const WRONG_DOMAIN = [
  "what's the weather like in Berlin?",
  "translate this paragraph to French",
  "tell me a joke",
  "who won the world cup last year?",
  "give me a poem about kittens",
  "what's a good recipe for lasagna?",
  "summarize the book Dune",
  "what's the meaning of life?",
];

const TECH_CLARIFICATIONS = [
  "yes I already tried that",
  "what should I check next?",
  "the error code is 0x80070005",
  "no, that didn't help",
  "I'm on a Mac, does that change things?",
  "this started after the last update",
  "I'm at the office on the corporate network",
];

const FRUSTRATED_REASKS = [
  "that's not what I'm asking",
  "you're not understanding me",
  "let me rephrase",
  "this isn't helpful",
];

// ── helpers ───────────────────────────────────────────────────────────────────

function pickUser() {
  return users[Math.floor(Math.random() * users.length)];
}

function ask(user, sessionId, conversationId, question) {
  const url = `${BASE}/api/ask`;
  const body = {
    question,
    session_id: sessionId,
    conversation_id: conversationId,
    employee_email: user.email,
    employee_name: user.name || user.email,
    role: user.role || 'ic',
  };
  const r = request('POST', url, body, user, sessionId, { timeout: '90s' });
  check(r, {
    'supportbot 2xx': (res) => res.status >= 200 && res.status < 300,
  });
  return r;
}

// ── journeys ──────────────────────────────────────────────────────────────────

function singleQA(user, pool) {
  const sessionId = randSessionId();
  const conversationId = randConversationId();
  request('GET', `${BASE}/`, null, user, sessionId);
  sleepStep();
  ask(user, sessionId, conversationId, pickOne(pool));
  sleepStep();
}

function journeyBilling(user) {
  group('billing', () => singleQA(user, BILLING_QUESTIONS));
}

function journeyTechEasy(user) {
  group('tech-easy', () => singleQA(user, TECH_QUESTIONS));
}

function journeyTechMultiTurn(user) {
  group('tech-multi', () => {
    const sessionId = randSessionId();
    const conversationId = randConversationId();
    request('GET', `${BASE}/`, null, user, sessionId);
    sleepStep();
    const turns = randInt(3, 5);
    ask(user, sessionId, conversationId, pickOne(TECH_QUESTIONS));
    sleepStep();
    for (let i = 1; i < turns; i++) {
      ask(user, sessionId, conversationId, pickOne(TECH_CLARIFICATIONS));
      sleepStep();
    }
  });
}

function journeyAccount(user) {
  group('account', () => singleQA(user, ACCOUNT_QUESTIONS));
}

function journeyWrongDomain(user) {
  group('wrong-domain', () => singleQA(user, WRONG_DOMAIN));
}

function journeyFrustrated(user) {
  group('frustrated', () => {
    const sessionId = randSessionId();
    const conversationId = randConversationId();
    request('GET', `${BASE}/`, null, user, sessionId);
    sleepStep();
    // Pick a pool at random for the original question, then re-ask with
    // frustrated follow-ups (does not change domain).
    const pool = pickOne([BILLING_QUESTIONS, TECH_QUESTIONS, ACCOUNT_QUESTIONS]);
    ask(user, sessionId, conversationId, pickOne(pool));
    sleepStep();
    ask(user, sessionId, conversationId, pickOne(FRUSTRATED_REASKS));
    sleepStep();
    ask(user, sessionId, conversationId, pickOne(pool));
    sleepPonder();
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
    { value: 'billing',    weight: 30 },
    { value: 'tech-easy',  weight: 25 },
    { value: 'tech-multi', weight: 15 },
    { value: 'account',    weight: 20 },
    { value: 'wrong',      weight: 5 },
    { value: 'frustrated', weight: 5 },
  ]);
  switch (journey) {
    case 'billing':    journeyBilling(user); break;
    case 'tech-easy':  journeyTechEasy(user); break;
    case 'tech-multi': journeyTechMultiTurn(user); break;
    case 'account':    journeyAccount(user); break;
    case 'wrong':      journeyWrongDomain(user); break;
    case 'frustrated': journeyFrustrated(user); break;
  }
}
