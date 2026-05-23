# Recommended Sigil evaluators

A curated set of LLM-judge and rule-based evaluators that turn the
ai-o11y-demo-apps stack into a complete AI o11y demo — not just metrics
and traces, but verdicts on whether the AI is actually doing its job
well.

All evaluators target the OTel GenAI semconv attributes the apps already
emit (`gen_ai.agent.name`, `gen_ai.conversation.id`, `gen_ai.user.id`,
prompt/response text). Apply them via Sigil:

```
POST {SIGIL_ENDPOINT}/api/plugins/grafana-sigil-app/resources/eval/evaluators
```

Or click-through: **Grafana → AI Observability → Evaluators → New evaluator**.

The 8 evaluators below cover every failure mode that matters for both
apps. Pick the 3-5 most relevant for your customer; running all 8 against
every conversation is overkill (and expensive).

> **Sigil template variables**: prompts below use `{{latest_user_message}}`,
> `{{assistant_response}}`, `{{tool_calls}}`, `{{tool_results}}`,
> `{{system_prompt}}`, `{{tools}}`, `{{assistant_sequence}}`, `{{stop_reason}}`,
> `{{call_error}}` — paste them verbatim into Sigil's User-prompt field.
>
> **Filters live on Rules, not Evaluators**: Sigil separates *the judge*
> (Evaluators tab) from *targeting* (Rules tab). Create the evaluator with
> just the prompt + scoring, then go to **Rules → New** and add the filter
> (e.g. `gen_ai.agent.name =~ "nc-.*"`) that wires that evaluator to the
> matching conversations.


---

## 1. NeonCart response quality (LLM-judge, 0-5)

**Why it matters:** answers the "is the AI actually helpful" question.
Cheap and broadly informative — start here.

**Filter:** `gen_ai.agent.name =~ "nc-.*"`

**Judge model:** `claude-haiku-4-5-20251001` (cheap, fast, good enough)

**Prompt template:**
```
You are evaluating an AI shopping assistant's response quality.

User asked: {{latest_user_message}}
AI responded: {{assistant_response}}
Tools used: {{tool_calls}}

Rate the response 0-5 on these dimensions, then average:
- RELEVANCE: did it actually address what the user asked?
- COMPLETENESS: did it give enough info to act on?
- ACCURACY: are the product details / prices / availability correct?
- TONE: is it appropriate for a shopping context (helpful, not pushy)?

Reply with JSON: {"score": <0-5>, "rationale": "<one sentence>"}
```

**Verdict scheme:** numeric 0.0-5.0, with `< 3.0 = fail`.

**Dashboard hook:** `sigil_eval_executions_total{evaluator="nc-quality",status="fail"}`

---

## 2. SupportBot response quality (LLM-judge, 0-5)

Same shape as #1 but for the internal helpdesk. Different filter +
prompt + tone criteria.

**Filter:** `gen_ai.agent.name =~ "sb-.*"`

**Prompt template:**
```
You are evaluating an internal employee help bot's response.

Employee asked: {{latest_user_message}}
Bot responded: {{assistant_response}}
Tools used: {{tool_calls}}

Rate 0-5:
- ACTIONABLE: did it tell the employee what to do, or just describe the situation?
- POLICY-ALIGNED: does the advice match company policy as referenced in tool outputs?
- COMPLETENESS: would the employee need to ask a follow-up to act?
- TONE: professional, not condescending, no excessive disclaimers?

Reply: {"score": <0-5>, "rationale": "<one sentence>"}
```

---

## 3. NeonCart groundedness (LLM-judge, pass/fail)

**Why it matters:** catches the failure mode where the AI invents SKUs,
prices, or availability that weren't returned by `search_products` /
`search_by_criteria`. THIS is the AI o11y demo punchline — "see how
groundedness drops the moment you switch models."

**Filter:** `gen_ai.agent.name =~ "nc-chatbot|nc-gift-finder"`

**Prompt template:**
```
You are verifying whether an AI shopping assistant's response is
grounded in the tool data it received.

Tool results (the catalog data the AI saw):
{{tool_calls}}

AI response to user:
{{assistant_response}}

A grounded response only mentions products / prices / specs that
appear in the tool results above. Inventing SKUs, prices, descriptions,
or availability not in the tool output = NOT grounded.

Reply: {"grounded": true|false, "ungrounded_claims": ["<claim 1>", ...]}
```

**Verdict:** boolean. Failing percentage on the dashboard is the headline
"AI hallucinates products" metric.

---

## 4. SupportBot groundedness (LLM-judge, pass/fail)

Same shape but for internal-bot. Critical because invented HR/IT policy
is a compliance issue.

**Filter:** `gen_ai.agent.name =~ "sb-billing|sb-tech-support|sb-account-management"`

**Prompt template:**
```
You are verifying an internal help bot grounded its answer in tool data.

Tools called: {{tool_calls}}  (e.g., search_runbook, lookup_employee_expense)
Bot response: {{assistant_response}}

If the bot cited a runbook step, expense amount, account detail, or
policy NOT present in the tool output, mark as NOT grounded.

Reply: {"grounded": true|false, "ungrounded_claims": [...]}
```

---

## 5. Hallucination check (both apps, LLM-judge, pass/fail)

A tighter version of groundedness that doesn't need tool output as
reference — useful for sessions with no tool calls.

**Filter:** `gen_ai.agent.name =~ "nc-.*|sb-.*"`

**Prompt template:**
```
Does this AI response contain any factual claim that:
- is fabricated (made up)
- contradicts widely known facts
- mentions specific identifiers (SKUs, dollar amounts, dates) that look
  invented rather than retrieved?

Prompt: {{latest_user_message}}
Response: {{assistant_response}}

Reply: {"hallucination": true|false, "examples": [...]}
```

---

## 6. PII detection in SupportBot responses (regex + LLM-judge, pass/fail)

**Why it matters:** internal bot has access to employee profiles. The
ONE thing it must never do is leak PII into a conversation log. This
evaluator catches it.

**Filter:** `gen_ai.agent.name =~ "sb-account-management|sb-billing"`

**Layer 1 — fast regex pre-screen** (catches obvious leaks cheaply):
```
PII regex patterns (any match flags for layer 2):
- SSN: \b\d{3}-\d{2}-\d{4}\b
- Credit card: \b(?:\d[ -]*?){13,16}\b
- Email: [a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}
- US phone: \b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b
- IP: \b(?:\d{1,3}\.){3}\d{1,3}\b
```

**Layer 2 — LLM-judge confirmation:**
```
Does this response contain PII (personally identifiable information)
that should not appear in a customer-facing or logged conversation?
PII = SSN, full credit card, home address, salary, full DOB, etc.

Bot response: {{assistant_response}}

Reply: {"contains_pii": true|false, "pii_types": ["ssn", "address", ...]}
```

**Why two layers:** regex is cheap and catches structured PII; LLM-judge
catches contextual PII the regex misses ("John Smith makes $145k" — no
regex hit but PII present).

---

## 7. Angry-customer detection on NeonCart (LLM-judge, sentiment)

**Why it matters:** the demo story includes the "frustrated journey"
loadgen path. This evaluator surfaces those interactions on the
dashboard for support-team review.

**Filter:** `gen_ai.agent.name =~ "nc-chatbot|nc-gift-finder"`

**Apply to the USER turn, not the AI response.**

**Prompt template:**
```
Classify the emotional state expressed in this customer message.

Message: {{latest_user_message}}

Categories:
- NEUTRAL: standard product question, no emotion
- POSITIVE: enthusiastic, complimentary
- FRUSTRATED: showing impatience, repeating themselves
- ANGRY: rude language, demanding human, threatening to leave

Reply: {"sentiment": "<category>", "confidence": 0.0-1.0, "trigger_phrases": [...]}
```

**Verdict scheme:** categorical. Dashboard splits "angry rate per
conversation" by `gen_ai.request.model` — does Sonnet handle angry
customers better than Haiku?

---

## 8. Tool-call correctness (rule-based, pass/fail)

**Why it matters:** catches the gateway-tool-routing bug class (LLM
hallucinates a tool name, passes wrong arg shape, etc.). Free / no LLM
call needed.

**Filter:** any agent with tools — `gen_ai.tool.name != ""`

**Rule:** match the tool call against the declared tool schema (already
known to the gateway). Verdict = `pass` if every called tool exists +
all required params provided + types match.

This is implementable as a pure-code evaluator (no LLM judge); cheap to
run on 100% of conversations.

---

## Suggested rollout order

1. **Start with #3 (groundedness) on NeonCart.** That's the single most
   demo-impactful eval — it visualizes the "AI making stuff up" failure
   mode directly, and the loadgen produces enough conversation diversity
   to show meaningful pass/fail rates per model.

2. Add **#1 (NC quality)** and **#2 (SB quality)** next — gives you the
   "overall AI health" KPI for the dashboard's top row.

3. **#6 (PII)** comes third — short demo runtime but lands the compliance
   beat for any internal-AI conversation.

4. **#7 (angry customer)** for the "AI conversation health" panel.

5. Everything else as time allows.

## How the dashboard uses these

The Use Cases dashboard's **Sigil Evaluations** row consumes:

```promql
# Pass rate per evaluator, per model
sum by (evaluator, gen_ai_request_model) (
  increase(sigil_eval_executions_total{
    service_namespace="ai-o11y-demo-apps",
    status="pass"
  }[1h])
)
/
sum by (evaluator, gen_ai_request_model) (
  increase(sigil_eval_executions_total{
    service_namespace="ai-o11y-demo-apps"
  }[1h])
)
```

Drop into a stat panel grouped by `evaluator`, color thresholds at 80%
and 95%. Tells the side-by-side "which model is best at X" story.

## Cost gotcha

LLM-judge evaluators run every conversation through a second LLM call.
At default loadgen volume (~3-5 conversations/min) and Haiku judge
pricing, expect ~$5-10/day per evaluator. Use the cheapest reasonable
judge model — Haiku 4.5 is the sweet spot. Don't use Opus as a judge;
the cost will dwarf the conversation cost it's evaluating.
