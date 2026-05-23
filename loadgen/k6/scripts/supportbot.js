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

// ── question pools (25-30 per domain) ─────────────────────────────────────────
//
// Real employee questions are messy: they include partial context, role
// pronouns ("my team", "our org"), error codes, and brand names. We bias
// pools toward that shape. ~3-5 entries per domain are intentionally
// open-ended / unanswerable from a stock FAQ so the bot lands on
// "I'll file a support ticket for you" — the realistic outcome.

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
  // — payroll/expense flavor (often routed through billing in real cos) —
  "my last paycheck was short, who do I talk to?",
  "how do I submit expenses for the offsite in Austin?",
  "can I get reimbursed for the home-office chair I bought?",
  "what's the per diem for international travel?",
  "I haven't received my W-2 yet",
  "I want to set up direct deposit to a second account",
  "how do I change my tax withholding?",
  "do I get reimbursed for cell phone or is there a stipend?",
  // — harder / unanswerable, should land on file-a-ticket —
  "finance flagged a $4,300 vendor charge from October — can you look?",
  "I think my bonus prorated wrong, can someone pull the math?",
  "the SaaS tool we use is double-billing the team for seats we cancelled",
  "I got an audit email from accounting and I have no idea what they want",
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
  // — laptop / dock / peripheral flavor —
  "my Thunderbolt dock stopped showing the external monitors after the update",
  "the trackpad on my macbook is acting glitchy, especially with two fingers",
  "my headset only plays audio out of one ear in zoom but works fine in spotify",
  "the office wifi keeps dropping me into a captive portal even after I sign in",
  "I plugged in a new yubikey and now my old one stopped working",
  "my battery drains to zero overnight even with the lid closed",
  "I'm getting kernel panics maybe twice a day, started this week",
  // — corporate-app errors —
  "slack keeps signing me out, no error, just back to the workspace picker",
  "I get a 403 trying to push to the internal gitlab",
  "okta says 'access denied' for our payroll app, worked yesterday",
  "Jira is throwing 502 every time I open a board",
  // — harder / unanswerable —
  "my whole team has been unable to deploy since 11am — incident or just us?",
  "the build server randomly drops connections to s3 but only for our region",
  "something is rewriting my .zshrc on every login, IT pushed something?",
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
  // — onboarding / offboarding —
  "a new hire starts Monday, what do I need to do to get them set up?",
  "I'm offboarding a contractor today, what's the checklist?",
  "how do I request a laptop for an incoming intern?",
  "where's the doc for setting up okta for a new starter?",
  "I need to revoke github access for someone who left last week",
  "do new hires get added to the all-hands calendar automatically?",
  // — permissions / groups —
  "I need read-only prod access for our SRE rotation",
  "how do I add my manager to the #leadership-private channel?",
  "what's the process for getting added to the finance group in google drive?",
  "I was moved to a new team but my old slack groups are still attached",
  // — harder / unanswerable —
  "someone on my team has the wrong job title in the directory and HR can't fix it",
  "I'm supposed to inherit a former-employee's confluence space — how?",
  "the org chart shows my dotted-line manager as my real manager, that wrong",
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
  "draft me a wedding speech for my brother",
  "what stocks should I buy this week?",
  "is it ok to text my ex on her birthday?",
  "write a haiku about Monday meetings",
];

const TECH_CLARIFICATIONS = [
  "yes I already tried that",
  "what should I check next?",
  "the error code is 0x80070005",
  "no, that didn't help",
  "I'm on a Mac, does that change things?",
  "this started after the last update",
  "I'm at the office on the corporate network",
  "ok I rebooted, same problem",
  "I'm seeing it on chrome but not safari",
  "the IT FAQ doesn't list this one",
  "it only happens when I'm on the VPN",
  "the logs say 'connection refused' if that helps",
  "I'm working from a coffee shop today, could that be it?",
  "I'm on the beta channel of the app",
];

const FRUSTRATED_REASKS = [
  "that's not what I'm asking",
  "you're not understanding me",
  "let me rephrase",
  "this isn't helpful",
  "I've been going in circles with you",
  "can a human take this one?",
  "you already suggested that, it didn't work",
];

// ── helpers ───────────────────────────────────────────────────────────────────

function pickUser() {
  return users[Math.floor(Math.random() * users.length)];
}

/**
 * Pick a journey weighted by the user's role so prompts feel role-coherent
 * to a Sigil reviewer. Finance/HR skew toward billing & account questions;
 * IC/contractor skew toward tech-support; managers + execs mix more evenly.
 * Falls back to the global default weights when the role is missing.
 */
function pickJourneyForRole(role) {
  const r = (role || 'ic').toLowerCase();
  if (r === 'finance') {
    return pickWeighted([
      { value: 'billing',    weight: 50 },
      { value: 'tech-easy',  weight: 15 },
      { value: 'tech-multi', weight: 8 },
      { value: 'account',    weight: 17 },
      { value: 'wrong',      weight: 5 },
      { value: 'frustrated', weight: 5 },
    ]);
  }
  if (r === 'hr') {
    return pickWeighted([
      { value: 'billing',    weight: 20 },
      { value: 'tech-easy',  weight: 15 },
      { value: 'tech-multi', weight: 5 },
      { value: 'account',    weight: 50 },
      { value: 'wrong',      weight: 5 },
      { value: 'frustrated', weight: 5 },
    ]);
  }
  if (r === 'ic' || r === 'contractor') {
    return pickWeighted([
      { value: 'billing',    weight: 15 },
      { value: 'tech-easy',  weight: 35 },
      { value: 'tech-multi', weight: 25 },
      { value: 'account',    weight: 15 },
      { value: 'wrong',      weight: 5 },
      { value: 'frustrated', weight: 5 },
    ]);
  }
  if (r === 'legal') {
    return pickWeighted([
      { value: 'billing',    weight: 30 },
      { value: 'tech-easy',  weight: 15 },
      { value: 'tech-multi', weight: 5 },
      { value: 'account',    weight: 35 },
      { value: 'wrong',      weight: 10 },
      { value: 'frustrated', weight: 5 },
    ]);
  }
  // manager / exec / unknown — closer to the org-wide default mix.
  return pickWeighted([
    { value: 'billing',    weight: 30 },
    { value: 'tech-easy',  weight: 25 },
    { value: 'tech-multi', weight: 15 },
    { value: 'account',    weight: 20 },
    { value: 'wrong',      weight: 5 },
    { value: 'frustrated', weight: 5 },
  ]);
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
  // ~30% of "single" Q&A sessions actually keep talking — a clarifying
  // follow-up in the same conversation. Drives realistic multi-turn density
  // without changing the journey-weights contract.
  if (Math.random() < 0.3) {
    ask(user, sessionId, conversationId, pickOne(TECH_CLARIFICATIONS));
    sleepStep();
  }
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
  // Role-aware journey selection (e.g., finance asks billing, IC asks tech).
  // Falls back to the global default mix for unknown/missing roles.
  const journey = pickJourneyForRole(user.role);
  switch (journey) {
    case 'billing':    journeyBilling(user); break;
    case 'tech-easy':  journeyTechEasy(user); break;
    case 'tech-multi': journeyTechMultiTurn(user); break;
    case 'account':    journeyAccount(user); break;
    case 'wrong':      journeyWrongDomain(user); break;
    case 'frustrated': journeyFrustrated(user); break;
  }
}
