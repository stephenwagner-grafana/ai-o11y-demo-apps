// Paste this whole block into your browser DevTools Console while logged in
// to your Grafana stack (any page works — uses window.location.origin).
// Creates / upserts all 18 Sigil evaluators (one is a joke — sbPirateMate) for the ai-o11y-demo-apps demo.
//
// Re-runs are safe: existing evaluators 409 / 400 with a clear message and
// the script keeps going.
//
// If your judge target differs from haiku, change JUDGE_PROVIDER / JUDGE_MODEL
// at the top of this block before pasting.
//
// Last verified: 2026-05-24 against Grafana Cloud Sigil plugin v0.x

(async () => {
  // ── Customize before pasting (if needed) ────────────────────────────────────
  const JUDGE_PROVIDER = "anthropic-vertex";   // or "anthropic"
  const JUDGE_MODEL    = "claude-sonnet-4-5";  // or "claude-haiku-4-5-20251001"
  const VERSION        = new Date().toISOString().slice(0, 10);  // YYYY-MM-DD

  // ── Helpers ─────────────────────────────────────────────────────────────────
  const URL = `${window.location.origin}/api/plugins/grafana-sigil-app/resources/eval/evaluators`;

  const llmJudge = (id, desc, sys, usr, output_keys, max_tokens = 256, pass_threshold, min, max) => {
    max_tokens = Math.max(256, max_tokens || 256);  // API minimum
    // For number output_keys, attach pass_threshold/min/max INSIDE the first key
    const keys = output_keys.map((k, i) => {
      if (i === 0 && k.type === "number") {
        const enriched = { ...k };
        if (pass_threshold !== undefined) enriched.pass_threshold = pass_threshold;
        if (min !== undefined) enriched.min = min;
        if (max !== undefined) enriched.max = max;
        return enriched;
      }
      return k;
    });
    return {
      evaluator_id: id, version: VERSION, kind: "llm_judge", description: desc,
      config: { provider: JUDGE_PROVIDER, model: JUDGE_MODEL,
                system_prompt: sys, user_prompt: usr,
                max_tokens, temperature: 0 },
      output_keys: keys,
    };
  };

  const regexEval = (id, desc, pattern) => ({
    evaluator_id: id, version: VERSION, kind: "regex", description: desc,
    config: { pattern, evaluate_against: "response" },
    output_keys: [{ key: "regex_match", type: "bool", pass_value: false }],
  });

  const jsonSchemaEval = (id, desc, schema) => ({
    evaluator_id: id, version: VERSION, kind: "json_schema", description: desc,
    config: { schema, evaluate_against: "response" },
    output_keys: [{ key: "json_valid", type: "bool", pass_value: true }],
  });

  const heuristicEval = (id, desc, root, output_key = "heuristic_pass") => ({
    evaluator_id: id, version: VERSION, kind: "heuristic", description: desc,
    config: { version: "v2", root },
    output_keys: [{ key: output_key, type: "bool", pass_value: true }],
  });

  // ── The 18 evaluators ───────────────────────────────────────────────────────
  const EVALUATORS = [
    llmJudge(
      "ncQuality",
      "0-5 quality score for nc-chatbot and nc-gift-finder responses (relevance, completeness, accuracy, tone).",
      "You evaluate one assistant response. Use only the user input and assistant output. Follow the score field description exactly. Be strict. If uncertain, choose the lower score.",
`You are evaluating an AI shopping assistant's response quality.

User asked: {{latest_user_message}}
AI responded: {{assistant_response}}
Tools used: {{tool_calls}}

Rate 0-5 on:
- RELEVANCE: did it address what the user asked?
- COMPLETENESS: enough info to act on?
- ACCURACY: are product details / prices / availability correct?
- TONE: helpful, not pushy?

Reply JSON only: {"score": <0.0-5.0>, "rationale": "<one sentence>"}`,
      [{ key: "score", type: "number" }],
      256, 3.0, 0, 5,
    ),
    llmJudge(
      "sbQuality",
      "0-5 quality score for sb-* agent responses (actionable, policy-aligned, complete, professional tone).",
      "You evaluate one assistant response. Use only the user input and assistant output. Follow the score field description exactly. Be strict. If uncertain, choose the lower score.",
`You are evaluating an internal employee help bot's response.

Employee asked: {{latest_user_message}}
Bot responded: {{assistant_response}}
Tools used: {{tool_calls}}

Rate 0-5:
- ACTIONABLE: did it tell the employee what to do, or just describe the situation?
- POLICY-ALIGNED: does the advice match company policy as referenced in tool outputs?
- COMPLETENESS: would the employee need to ask a follow-up to act?
- TONE: professional, not condescending, no excessive disclaimers?

Reply JSON only: {"score": <0.0-5.0>, "rationale": "<one sentence>"}`,
      [{ key: "score", type: "number" }],
      256, 3.0, 0, 5,
    ),
    llmJudge(
      "ncGroundedness",
      "Boolean: did the NC chatbot/gift-finder use only catalog data returned by its tools, or did it hallucinate products?",
      "You verify whether an AI response is grounded in tool data only. Be strict: if a product SKU, price, spec, or availability claim does not appear VERBATIM in the tool results, mark it as ungrounded. Do not give the response benefit of the doubt. Reply with valid JSON only — no prose outside the JSON object.",
`You are verifying whether an AI shopping assistant's response is grounded
in the tool data it received.

Tool results: {{tool_results}}
AI response: {{assistant_response}}

A grounded response only mentions products / prices / specs that appear
in the tool results above. Inventing SKUs, prices, descriptions, or
availability NOT in the tool output = NOT grounded.

Reply JSON only: {"grounded": <true|false>, "ungrounded_claims": ["<claim 1>", ...]}`,
      [{ key: "grounded", type: "bool", pass_value: true }],
      300,
    ),
    llmJudge(
      "sbGroundedness",
      "Boolean: did the SB specialist use only data returned by its tools, or did it invent policy/details?",
      "You verify whether an internal help bot grounded its answer in tool data only. Be strict: if a runbook step, expense amount, account detail, or policy claim does not appear VERBATIM in the tool output, mark it as ungrounded. Compliance-critical — err on the strict side. Reply with valid JSON only.",
`You are verifying an internal help bot grounded its answer in tool data.

Tools called: {{tool_calls}}
Tool results: {{tool_results}}
Bot response: {{assistant_response}}

If the bot cited a runbook step, expense amount, account detail, or policy
NOT present in the tool output, mark as NOT grounded.

Reply JSON only: {"grounded": <true|false>, "ungrounded_claims": [...]}`,
      [{ key: "grounded", type: "bool", pass_value: true }],
      300,
    ),
    llmJudge(
      "hallucination",
      "Boolean: did the AI response invent facts, contradict known information, or fabricate identifiers?",
      "You are a fact-checker. Flag any claim in the AI response that is fabricated, contradicts widely-known facts, or contains specific identifiers (SKUs, dollar amounts, dates) that look invented rather than retrieved. Err on the side of flagging. Reply with valid JSON only.",
`Does this AI response contain any factual claim that:
- is fabricated (made up)
- contradicts widely known facts
- mentions specific identifiers (SKUs, dollar amounts, dates) that look
  invented rather than retrieved?

Prompt: {{latest_user_message}}
Response: {{assistant_response}}

Reply JSON only: {"hallucination": <true|false>, "examples": [...]}`,
      [{ key: "hallucination", type: "bool", pass_value: false }],
      300,
    ),
    regexEval("piiSsn",        "Matches a US Social Security Number in the format NNN-NN-NNNN.",                       "\\b\\d{3}-\\d{2}-\\d{4}\\b"),
    regexEval("piiCreditCard", "Matches a 13-16 digit credit card number with optional spaces or dashes.",            "\\b(?:\\d[ -]*?){13,16}\\b"),
    regexEval("piiEmail",      "Matches an email address.",                                                            "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}"),
    regexEval("piiPhone",      "Matches a US phone number with or without country code.",                              "\\b(?:\\+?1[-.\\s]?)?\\(?\\d{3}\\)?[-.\\s]?\\d{3}[-.\\s]?\\d{4}\\b"),
    regexEval("piiIp",         "Matches an IPv4 address.",                                                             "\\b(?:\\d{1,3}\\.){3}\\d{1,3}\\b"),
    heuristicEval(
      "sbPii",
      "Pass if none of 5 PII patterns (SSN, credit card, email, phone, IPv4) match the bot's response.",
      {
        kind: "group",
        operator: "and",
        rules: [
          { kind: "rule", type: "regex_no_match", value: "\\b\\d{3}-\\d{2}-\\d{4}\\b" },
          { kind: "rule", type: "regex_no_match", value: "\\b(?:\\d[ -]*?){13,16}\\b" },
          { kind: "rule", type: "regex_no_match", value: "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}" },
          { kind: "rule", type: "regex_no_match", value: "\\b(?:\\+?1[-.\\s]?)?\\(?\\d{3}\\)?[-.\\s]?\\d{3}[-.\\s]?\\d{4}\\b" },
          { kind: "rule", type: "regex_no_match", value: "\\b(?:\\d{1,3}\\.){3}\\d{1,3}\\b" },
        ],
      },
    ),
    llmJudge(
      "ncSentiment",
      "Categorical sentiment of the user's message (NEUTRAL / POSITIVE / FRUSTRATED / ANGRY).",
      "You are a sentiment classifier. Classify only the customer message. Be strict about boundaries: NEUTRAL is the default; pick FRUSTRATED or ANGRY only when there is clear language of impatience, rudeness, or escalation. Reply with valid JSON only.",
`Classify the emotional state expressed in this customer message.

Message: {{latest_user_message}}

Categories:
- NEUTRAL: standard product question, no emotion
- POSITIVE: enthusiastic, complimentary
- FRUSTRATED: showing impatience, repeating themselves
- ANGRY: rude language, demanding human, threatening to leave

Reply JSON only: {"sentiment": "<category>", "confidence": <0.0-1.0>, "trigger_phrases": [...]}`,
      [{ key: "sentiment", type: "string" }],
      256,
    ),
    llmJudge(
      "sbAiUsage",
      "Was this a worthwhile use of the SupportBot? Flag wasteful / trivial / abusive employee prompts.",
      "You are reviewing whether an Acme employee's question to the internal help bot was a productive use of AI. Be honest. Many prompts are perfectly legit; some are wasteful (could be Googled in 5s), some are abusive (chit-chat, gaming the system, irrelevant). Reply with valid JSON only — no prose outside the JSON object.",
`Classify the employee's use of the AI help bot.

Employee message: {{latest_user_message}}
Tools the bot would consult: {{tools}}

Categories:
- WORTHY: legitimate question that benefits from the bot's tools (runbooks, expense lookup, account info, internal policy)
- BORDERLINE: answerable via a 10-second web search or existing docs; using AI is OK but inefficient
- WASTEFUL: trivial, social, or off-topic — the bot adds no value
- ABUSIVE: gaming the system, irrelevant requests, or attempts to extract data the employee shouldn't see

Reply JSON only: {"usage": "<category>", "confidence": <0.0-1.0>, "rationale": "<one sentence>"}`,
      [{ key: "usage", type: "string" }],
      256,
    ),
    llmJudge(
      "ncConciseness",
      "Boolean: was the NC chatbot/gift-finder response concise and on-point (no preamble, no fluff)?",
      "You are a writing critic. A concise response answers the question directly without filler, recap of the question, multi-paragraph context, or excessive disclaimers. Be strict: 'Great question!' or 'Sure, I can help with that' is a fail. Reply with valid JSON only.",
`Is this AI response appropriately concise?

User asked: {{latest_user_message}}
AI responded: {{assistant_response}}

A response is CONCISE if:
- Answers the question directly within 1-3 sentences (or a short bullet list)
- No "Great question!" / "Sure, I can help" preamble
- No re-statement of the question
- No unsolicited follow-up suggestions or upsells
- No disclaimers ("As an AI..." / "Please note...")

Reply JSON only: {"concise": <true|false>, "padding_examples": ["<phrase>", ...]}`,
      [{ key: "concise", type: "bool", pass_value: true }],
      256,
    ),
    llmJudge(
      "sbConciseness",
      "Boolean: was the SB specialist response concise (employees want answers, not essays)?",
      "You are a writing critic for an internal help bot. Acme employees want direct answers, not preamble or essay-length explanations. Be strict: a response with 'I'd be happy to help!' or excessive disclaimers fails. Reply with valid JSON only.",
`Is this internal help bot response appropriately concise?

Employee asked: {{latest_user_message}}
Bot responded: {{assistant_response}}

A response is CONCISE if:
- Provides the answer / next action in the first sentence
- No "I'd be happy to help" / "Let me look that up" preamble
- No restating of company policy the employee already knows
- No "If you need further assistance, please..." closer

Reply JSON only: {"concise": <true|false>, "padding_examples": ["<phrase>", ...]}`,
      [{ key: "concise", type: "bool", pass_value: true }],
      256,
    ),
    llmJudge(
      "sbBrandVoice",
      "Boolean: does the SB specialist speak like an internal teammate using Acme terminology, NOT a sales rep pitching the employee?",
      "You audit whether an internal help bot speaks in the right voice. It should sound like a knowledgeable Acme teammate — concrete, factual, uses internal terminology (Acme HR portal, Acme expense system, Acme runbook, etc.). It should NOT pitch / upsell / use marketing language ('amazing', 'incredible', 'leverage', 'unlock', 'you'll love'). Reply with valid JSON only.",
`Does this internal help bot response sound like an Acme teammate, or like a marketing pitch?

Employee asked: {{latest_user_message}}
Bot responded: {{assistant_response}}

A response PASSES voice check if:
- Uses Acme-specific terminology when relevant (e.g. "Acme HR portal", "Acme expense system") instead of generic phrases
- Reads like an internal helpdesk reply: concrete, factual, action-oriented
- Does NOT pitch products, upsell features, or use marketing adjectives ("amazing", "powerful", "robust", "leverage", "unlock", "best-in-class")
- Does NOT address the employee like a prospect ("you'll love...", "discover...", "experience...")

Reply JSON only: {"on_brand": <true|false>, "violations": ["<marketing phrase or generic substitute>", ...]}`,
      [{ key: "on_brand", type: "bool", pass_value: true }],
      300,
    ),
    llmJudge(
      "sbPirateMate",
      "[Demo gag] 0-10 score: how likely is this Acme employee to abandon their cubicle and join you as first mate on a pirate ship?",
      "You are a pirate captain evaluating employees for first-mate potential. Score honestly based ONLY on what their message reveals. Look for: boldness of question, willingness to take initiative, healthy disregard for bureaucracy, mention of swashbuckling vocabulary, sense of adventure, OR conversely — extreme corporate compliance, fear of risk, deep love of TPS reports (auto-disqualifies). Reply with valid JSON only. Yes this is a joke evaluator. Take it seriously anyway.",
`Score this employee's first-mate-on-a-pirate-ship potential.

Employee asked: {{latest_user_message}}

Rate 0-10 across these dimensions, then average and round:
- BOLDNESS: does the question suggest a curious, risk-tolerant mind? (Or are they asking 'how do I file form 27B/6')
- INITIATIVE: would they grab the wheel in a storm, or wait for IT to fix it?
- ANTI-BUREAUCRACY: are they grudgingly compliant, or do they sound like they enjoy the expense report form?
- SWASHBUCKLE QUOTIENT: bonus points for any maritime / piratical / treasure-related vocabulary
- LOYALTY VECTOR: does their tone suggest they'd back you up against the Royal Navy?

Auto-disqualifiers (score 0): mentions of "synergy", "circling back", "let's take this offline", or unironic use of "ROI"
Auto-promoters (bonus to 10): mentions of "treasure", "ye", "captain", "the high seas", or any 'arrr'

Reply JSON only: {"first_mate_score": <0-10>, "verdict": "<one-line pirate captain's log entry>", "auto_flags": ["<flag1>", ...]}`,
      [{ key: "first_mate_score", type: "number" }],
      250, 7, 0, 10,
    ),
    jsonSchemaEval("jsonValid", "True if the assistant response is valid JSON.", {}),
  ];

  // ── POST each one ───────────────────────────────────────────────────────────
  console.log(`%cCreating ${EVALUATORS.length} evaluators on ${window.location.origin}`,
              "font-weight: bold; color: #00f0ff;");
  console.log(`Judge target: ${JUDGE_PROVIDER} / ${JUDGE_MODEL}`);

  const results = { ok: [], fail: [] };
  for (const ev of EVALUATORS) {
    try {
      const r = await fetch(URL, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify(ev),
      });
      const text = await r.text();
      if (r.ok) {
        console.log(`%c  ✓ ${ev.evaluator_id.padEnd(18)} ${ev.kind.padEnd(12)} HTTP ${r.status}`,
                    "color: #39ff7e;");
        results.ok.push(ev.evaluator_id);
      } else {
        console.log(`%c  ✗ ${ev.evaluator_id.padEnd(18)} ${ev.kind.padEnd(12)} HTTP ${r.status}`,
                    "color: #ff3b6b;");
        console.log(`      ${text.slice(0, 300)}`);
        results.fail.push({ id: ev.evaluator_id, status: r.status, body: text });
      }
    } catch (e) {
      console.log(`%c  ✗ ${ev.evaluator_id} threw: ${e.message}`, "color: #ff3b6b;");
      results.fail.push({ id: ev.evaluator_id, error: e.message });
    }
  }

  console.log(`\n%c${results.ok.length} created, ${results.fail.length} failed`,
              "font-weight: bold; color: #b537ff;");
  if (results.fail.length) console.table(results.fail);
  console.log("Next: create matching Rules in the Sigil UI (docs/EVALS.md has the per-evaluator Rule config).");
  return results;
})();
