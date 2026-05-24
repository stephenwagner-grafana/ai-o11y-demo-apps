# Recommended Sigil evaluators

A curated set of evaluators that turn the ai-o11y-demo-apps stack into a
complete AI o11y demo — not just metrics and traces, but verdicts on
whether the AI is actually doing its job well.

## 🚀 One-shot install (script all 18 evaluators (one is a joke))

Skip the UI walkthrough and create all 18 evaluators (one is a joke) via API:

```bash
export GRAFANA_URL=https://YOUR-STACK.grafana.net
export GRAFANA_API_TOKEN=glsa_xxxxxxxx   # service-account token

python3 tools/create-evaluators.py
```

Optional flags:
- `--judge-provider anthropic-vertex` to override the judge target
- `--judge-model claude-sonnet-4-5` (defaults to haiku for cost)
- `--only ncQuality ncGroundedness` to create a subset
- `--dry-run` to print payloads without POSTing

POSTs to `/api/plugins/grafana-sigil-app/resources/eval/evaluators` for
each. Rules still need to be created in the UI (see field tables below
per evaluator) — the public Rules API isn't documented yet.

---

## How Sigil's evaluator UI works

**Two-step model:**

1. **Evaluators** tab → define the judge logic (LLM-judge prompt, regex,
   JSON schema, or rule-based heuristic). An evaluator on its own does
   nothing — it's a function waiting for input.
2. **Rules** tab → wire one or more evaluators to a slice of your traffic
   (filter by agent name / model / etc.) at a sample rate. The rule
   selects which generations to score and which evaluator(s) to score
   them with.

Pick the 3-5 most relevant evaluators for your customer; running all 8 against every conversation is overkill (and expensive at LLM-judge cost).


> **Sigil ID format**: Evaluator ID and Rule ID fields accept only letters,
> digits, `_`, and `.` — no hyphens. We use dot-separated IDs throughout
> (matches Sigil's built-in convention like `online.helpfulness.user_visible`).

## The 4 evaluator Kinds Sigil supports

| Kind | What it does | Cost per call |
|---|---|---|
| **LLM Judge** | Prompts a model to score the response with rationale. Returns number / bool / string per your schema. | ~$0.001-0.01 (Haiku) |
| **JSON Schema** | Validates response is well-formed JSON against an optional schema. Returns bool. | Free |
| **Regex** | Pattern-matches the response. Sigil's "sparkle" icon turns a natural-language description into the regex for you. Returns bool. | Free |
| **Heuristic** | Combines other evaluator results with nested AND/OR groups. Up to 25 nodes, depth 3. Returns bool. | Free |

## Sigil evaluator template variables (LLM-judge User-prompt only)

Sigil substitutes these `{{double-brace}}` variables at evaluation time:

| Variable | What it expands to |
|---|---|
| `{{latest_user_message}}` | The most recent user-turn text |
| `{{assistant_response}}` | The AI's reply text |
| `{{system_prompt}}` | The system prompt sent to the model |
| `{{tool_calls}}` | Tool invocations the model made |
| `{{tool_results}}` | Output returned from tool execution |
| `{{tools}}` | Tool schemas the model had access to |
| `{{assistant_sequence}}` | Multi-step assistant turns concatenated |
| `{{stop_reason}}` | Why the generation ended |
| `{{call_error}}` | Error details if the generation failed |

---

## The 12 recommended evaluators

Each evaluator block maps 1:1 to the Sigil Create-evaluator form: paste the
"Field values" table values into the matching form fields, then create the
matching Rule on the Rules tab.

---

### 1. NeonCart response quality (LLM Judge, 0-5)

**Why it matters:** answers the "is the AI actually helpful" question. Cheap and broadly informative — start here.

| Field | Value |
|---|---|
| Kind | `LLM Judge` |
| Evaluator ID | `nc.quality` |
| Description | `0-5 quality score for nc-chatbot and nc-gift-finder responses (relevance, completeness, accuracy, tone).` |
| Provider | `Default` |
| Model | `Default (cheap haiku) |
| System prompt | `You evaluate one assistant response. Use only the user input and assistant output. Follow the score field description exactly. Be strict. If uncertain, choose the lower score.` |
| User prompt | *(paste the block below)* |
| Max tokens | `200` |
| Temperature | `0` |
| Output key | `score` |
| Output type | `number` |
| Output description | `Quality score 0.0-5.0` |
| Pass threshold | `3` |
| Min | `0` |
| Max | `5` |

**User prompt:**
```
You are evaluating an AI shopping assistant's response quality.

User asked: {{latest_user_message}}
AI responded: {{assistant_response}}
Tools used: {{tool_calls}}

Rate 0-5 on:
- RELEVANCE: did it address what the user asked?
- COMPLETENESS: enough info to act on?
- ACCURACY: are product details / prices / availability correct?
- TONE: helpful, not pushy?

Reply JSON only: {"score": <0.0-5.0>, "rationale": "<one sentence>"}
```

**Matching Rule** (Rules tab → Create Rule):

| Field | Value |
|---|---|
| Enable rule | ON |
| Rule ID | `online.nc.quality.user_visible` |
| Selector | `User-visible turn` |
| Match criteria | `gen_ai.agent.name =~ "nc-.*"` (Add criteria) |
| Sample rate | `10 (%) |
| Evaluators | `nc.quality` |

📋 **Quick copy-paste cheat:**

```yaml
# Evaluator
Kind: LLM Judge
Evaluator ID: nc.quality
Description: 0-5 quality score for nc-chatbot and nc-gift-finder responses (relevance, completeness, accuracy, tone).
Provider: Default
Model: Default (cheap haiku)
System prompt: You evaluate one assistant response. Use only the user input and assistant output. Follow the score field description exactly. Be strict. If uncertain, choose the lower score.
Max tokens: 200
Temperature: 0
Output key: score
Output type: number
Output description: Quality score 0.0-5.0
Pass threshold: 3
Min: 0
Max: 5
User prompt: |
  You are evaluating an AI shopping assistant's response quality.
  
  User asked: {{latest_user_message}}
  AI responded: {{assistant_response}}
  Tools used: {{tool_calls}}
  
  Rate 0-5 on:
  - RELEVANCE: did it address what the user asked?
  - COMPLETENESS: enough info to act on?
  - ACCURACY: are product details / prices / availability correct?
  - TONE: helpful, not pushy?
  
  Reply JSON only: {"score": <0.0-5.0>, "rationale": "<one sentence>"}

# Rule
Enable rule: ON
Rule ID: online.nc.quality.user_visible
Selector: User-visible turn
Match criteria: gen_ai.agent.name =~ "nc-.*"` (Add criteria)
Sample rate: 10 (%)
Evaluators: nc.quality
```

---

### 2. SupportBot response quality (LLM Judge, 0-5)

Same shape as #1 but for the internal helpdesk. Different filter + prompt + tone criteria.

| Field | Value |
|---|---|
| Kind | `LLM Judge` |
| Evaluator ID | `sb.quality` |
| Description | `0-5 quality score for sb-* agent responses (actionable, policy-aligned, complete, professional tone).` |
| System prompt | *(same as #1)* |
| User prompt | *(paste below)* |
| Max tokens | `200` |
| Temperature | `0` |
| Output key | `score` |
| Output type | `number` |
| Pass threshold | `3` |
| Min | `0` / Max | `5` |

**User prompt:**
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

Reply JSON only: {"score": <0.0-5.0>, "rationale": "<one sentence>"}
```

**Matching Rule:**

| Field | Value |
|---|---|
| Rule ID | `online.sb.quality.user_visible` |
| Selector | `User-visible turn` |
| Match criteria | `gen_ai.agent.name =~ "sb-.*"` |
| Sample rate | `10` |
| Evaluators | `sb.quality` |

📋 **Quick copy-paste cheat:**

```yaml
# Evaluator
Kind: LLM Judge
Evaluator ID: sb.quality
Description: 0-5 quality score for sb-* agent responses (actionable, policy-aligned, complete, professional tone).
Max tokens: 200
Temperature: 0
Output key: score
Output type: number
Pass threshold: 3
User prompt: |
  You are evaluating an internal employee help bot's response.
  
  Employee asked: {{latest_user_message}}
  Bot responded: {{assistant_response}}
  Tools used: {{tool_calls}}
  
  Rate 0-5:
  - ACTIONABLE: did it tell the employee what to do, or just describe the situation?
  - POLICY-ALIGNED: does the advice match company policy as referenced in tool outputs?
  - COMPLETENESS: would the employee need to ask a follow-up to act?
  - TONE: professional, not condescending, no excessive disclaimers?
  
  Reply JSON only: {"score": <0.0-5.0>, "rationale": "<one sentence>"}

# Rule
Rule ID: online.sb.quality.user_visible
Selector: User-visible turn
Match criteria: gen_ai.agent.name =~ "sb-.*"
Sample rate: 10
Evaluators: sb.quality
```

---

### 3. NeonCart groundedness (LLM Judge, pass/fail)

**Why it matters:** catches the failure mode where the AI invents SKUs, prices, or availability not in the tool output. The AI o11y demo punchline — "see how groundedness drops the moment you switch models."

| Field | Value |
|---|---|
| Kind | `LLM Judge` |
| Evaluator ID | `nc.groundedness` |
| Description | `Boolean: did the NC chatbot/gift-finder use only catalog data returned by its tools, or did it hallucinate products?` |
| System prompt | *(paste below)* |
| User prompt | *(paste below)* |
| Max tokens | `300` |
| Temperature | `0` |
| Output key | `grounded` |
| Output type | `bool` |
| Pass when | `true` |

**System prompt:**
```
You verify whether an AI response is grounded in tool data only. Be strict: if a product SKU, price, spec, or availability claim does not appear VERBATIM in the tool results, mark it as ungrounded. Do not give the response benefit of the doubt. Reply with valid JSON only — no prose outside the JSON object.
```

**User prompt:**
```
You are verifying whether an AI shopping assistant's response is grounded
in the tool data it received.

Tool results: {{tool_results}}
AI response: {{assistant_response}}

A grounded response only mentions products / prices / specs that appear
in the tool results above. Inventing SKUs, prices, descriptions, or
availability NOT in the tool output = NOT grounded.

Reply JSON only: {"grounded": <true|false>, "ungrounded_claims": ["<claim 1>", ...]}
```

**Matching Rule:**

| Field | Value |
|---|---|
| Rule ID | `online.nc.groundedness` |
| Selector | `User-visible turn` |
| Match criteria | `gen_ai.agent.name =~ "nc-chatbot|nc-gift-finder"` |
| Sample rate | `15` |
| Evaluators | `nc.groundedness` |

📋 **Quick copy-paste cheat:**

```yaml
# Evaluator
Kind: LLM Judge
Evaluator ID: nc.groundedness
System prompt: |
  You verify whether an AI response is grounded in tool data only. Be strict: if a product SKU, price, spec, or availability claim does not appear VERBATIM in the tool results, mark it as ungrounded. Do not give the response benefit of the doubt. Reply with valid JSON only — no prose outside the JSON object.
Description: Boolean: did the NC chatbot/gift-finder use only catalog data returned by its tools, or did it hallucinate products?
Max tokens: 300
Temperature: 0
Output key: grounded
Output type: bool
Pass when: true
User prompt: |
  You are verifying whether an AI shopping assistant's response is grounded
  in the tool data it received.
  
  Tool results: {{tool_results}}
  AI response: {{assistant_response}}
  
  A grounded response only mentions products / prices / specs that appear
  in the tool results above. Inventing SKUs, prices, descriptions, or
  availability NOT in the tool output = NOT grounded.
  
  Reply JSON only: {"grounded": <true|false>, "ungrounded_claims": ["<claim 1>", ...]}

# Rule
Rule ID: online.nc.groundedness
Selector: User-visible turn
Sample rate: 15
Evaluators: nc.groundedness
```

---

### 4. SupportBot groundedness (LLM Judge, pass/fail)

Critical because invented HR/IT policy is a compliance issue.

| Field | Value |
|---|---|
| Kind | `LLM Judge` |
| Evaluator ID | `sb.groundedness` |
| System prompt | *(paste below)* |
| Output key | `grounded` |
| Output type | `bool` |
| Pass when | `true` |

**System prompt:**
```
You verify whether an internal help bot grounded its answer in tool data only. Be strict: if a runbook step, expense amount, account detail, or policy claim does not appear VERBATIM in the tool output, mark it as ungrounded. Compliance-critical — err on the strict side. Reply with valid JSON only.
```

**User prompt:**
```
You are verifying an internal help bot grounded its answer in tool data.

Tools called: {{tool_calls}}
Tool results: {{tool_results}}
Bot response: {{assistant_response}}

If the bot cited a runbook step, expense amount, account detail, or policy
NOT present in the tool output, mark as NOT grounded.

Reply JSON only: {"grounded": <true|false>, "ungrounded_claims": [...]}
```

**Matching Rule:**

| Field | Value |
|---|---|
| Rule ID | `online.sb.groundedness` |
| Selector | `User-visible turn` |
| Match criteria | `gen_ai.agent.name =~ "sb-billing|sb-tech-support|sb-account-management"` |
| Sample rate | `15` |
| Evaluators | `sb.groundedness` |

📋 **Quick copy-paste cheat:**

```yaml
# Evaluator
Kind: LLM Judge
Evaluator ID: sb.groundedness
System prompt: |
  You verify whether an internal help bot grounded its answer in tool data only. Be strict: if a runbook step, expense amount, account detail, or policy claim does not appear VERBATIM in the tool output, mark it as ungrounded. Compliance-critical — err on the strict side. Reply with valid JSON only.
Output key: grounded
Output type: bool
Pass when: true
User prompt: |
  You are verifying an internal help bot grounded its answer in tool data.
  
  Tools called: {{tool_calls}}
  Tool results: {{tool_results}}
  Bot response: {{assistant_response}}
  
  If the bot cited a runbook step, expense amount, account detail, or policy
  NOT present in the tool output, mark as NOT grounded.
  
  Reply JSON only: {"grounded": <true|false>, "ungrounded_claims": [...]}

# Rule
Rule ID: online.sb.groundedness
Selector: User-visible turn
Sample rate: 15
Evaluators: sb.groundedness
```

---

### 5. Hallucination check (LLM Judge, pass/fail)

A tighter version that doesn't need tool output as reference — useful for sessions with no tool calls.

| Field | Value |
|---|---|
| Kind | `LLM Judge` |
| Evaluator ID | `hallucination` |
| System prompt | *(paste below)* |
| Output key | `hallucination` |
| Output type | `bool` |
| Pass when | `false (no hallucination = pass) |

**System prompt:**
```
You are a fact-checker. Flag any claim in the AI response that is fabricated, contradicts widely-known facts, or contains specific identifiers (SKUs, dollar amounts, dates) that look invented rather than retrieved. Err on the side of flagging. Reply with valid JSON only.
```

**User prompt:**
```
Does this AI response contain any factual claim that:
- is fabricated (made up)
- contradicts widely known facts
- mentions specific identifiers (SKUs, dollar amounts, dates) that look
  invented rather than retrieved?

Prompt: {{latest_user_message}}
Response: {{assistant_response}}

Reply JSON only: {"hallucination": <true|false>, "examples": [...]}
```

**Matching Rule:**

| Field | Value |
|---|---|
| Rule ID | `online.hallucination` |
| Selector | `User-visible turn` |
| Match criteria | `gen_ai.agent.name =~ "nc-.*|sb-.*"` |
| Sample rate | `5` |
| Evaluators | `hallucination` |

📋 **Quick copy-paste cheat:**

```yaml
# Evaluator
Kind: LLM Judge
Evaluator ID: hallucination
System prompt: |
  You are a fact-checker. Flag any claim in the AI response that is fabricated, contradicts widely-known facts, or contains specific identifiers (SKUs, dollar amounts, dates) that look invented rather than retrieved. Err on the side of flagging. Reply with valid JSON only.
Output key: hallucination
Output type: bool
Pass when: false (no hallucination = pass)
User prompt: |
  Does this AI response contain any factual claim that:
  - is fabricated (made up)
  - contradicts widely known facts
  - mentions specific identifiers (SKUs, dollar amounts, dates) that look
    invented rather than retrieved?
  
  Prompt: {{latest_user_message}}
  Response: {{assistant_response}}
  
  Reply JSON only: {"hallucination": <true|false>, "examples": [...]}

# Rule
Rule ID: online.hallucination
Selector: User-visible turn
Sample rate: 5
Evaluators: hallucination
```

---

### 6. PII detection in SupportBot responses (Regex + Heuristic combo, pass/fail)

**Why it matters:** internal bot has access to employee profiles. The ONE thing it must never do is leak PII into a conversation log.

Sigil's Regex evaluator checks one pattern per evaluator. Create one per PII type, then combine them in a Heuristic that fails if any match.

#### 6a. Create five Regex evaluators

For each row below, **Kind: Regex**, **Evaluate against: Response**, **Output type: bool**, **Pass when: false** (no match = pass).

Click the **sparkle** ✨ icon next to Pattern to auto-generate the regex from the natural-language description.

| Evaluator ID | Pattern description (paste verbatim) |
|---|---|
| `pii.ssn` | `Matches a US Social Security Number in the format NNN-NN-NNNN` |
| `pii.credit_card` | `Matches a 13-16 digit credit card number with optional spaces or dashes` |
| `pii.email` | `Matches an email address` |
| `pii.phone` | `Matches a US phone number with or without country code` |
| `pii.ip` | `Matches an IPv4 address` |

#### 6b. Combine with a Heuristic

| Field | Value |
|---|---|
| Kind | `Heuristic` |
| Evaluator ID | `sb.pii` |
| Description | `Pass if NONE of the PII regex evaluators matched the response.` |
| Output key | `heuristic_pass` |
| Output type | `bool` |
| Pass when | `true` |

In the Heuristic configuration: choose **All of**, then add 5 rules — for each PII regex evaluator above, select it from the dropdown (in place of `Response`) with the condition `is not match`.

**Matching Rule:**

| Field | Value |
|---|---|
| Rule ID | `online.sb.pii` |
| Selector | `User-visible turn` |
| Match criteria | `gen_ai.agent.name =~ "sb-account-management|sb-billing"` |
| Sample rate | `100 (PII is compliance — score every response) |
| Evaluators | `sb.pii` only (the 5 sub-evaluators chain in automatically) |

📋 **Quick copy-paste cheat:**

```yaml
# Evaluator
Kind: Heuristic
Evaluator ID: sb.pii
Description: Pass if NONE of the PII regex evaluators matched the response.
Output key: heuristic_pass
Output type: bool
Pass when: true

# Rule
Rule ID: online.sb.pii
Selector: User-visible turn
Sample rate: 100 (PII is compliance — score every response)
Evaluators: sb.pii` only (the 5 sub-evaluators chain in automatically)
```

---

### 7. Angry-customer detection on NeonCart (LLM Judge, categorical)

**Why it matters:** the demo story includes the "frustrated journey" loadgen path. This evaluator surfaces those interactions on the dashboard for support-team review.

Applies to the **user** turn (not the AI response).

| Field | Value |
|---|---|
| Kind | `LLM Judge` |
| Evaluator ID | `nc.sentiment` |
| Description | `Categorical sentiment of the user's message (NEUTRAL / POSITIVE / FRUSTRATED / ANGRY).` |
| System prompt | *(paste below)* |
| Output key | `sentiment` |
| Output type | `string` |
| Pass when | leave blank — this is categorical, dashboard charts the breakdown |

**System prompt:**
```
You are a sentiment classifier. Classify only the customer message. Be strict about boundaries: NEUTRAL is the default; pick FRUSTRATED or ANGRY only when there is clear language of impatience, rudeness, or escalation. Reply with valid JSON only.
```

**User prompt:**
```
Classify the emotional state expressed in this customer message.

Message: {{latest_user_message}}

Categories:
- NEUTRAL: standard product question, no emotion
- POSITIVE: enthusiastic, complimentary
- FRUSTRATED: showing impatience, repeating themselves
- ANGRY: rude language, demanding human, threatening to leave

Reply JSON only: {"sentiment": "<category>", "confidence": <0.0-1.0>, "trigger_phrases": [...]}
```

**Matching Rule:**

| Field | Value |
|---|---|
| Rule ID | `online.nc.sentiment` |
| Selector | `User-visible turn` |
| Match criteria | `gen_ai.agent.name =~ "nc-chatbot|nc-gift-finder"` |
| Sample rate | `25` |
| Evaluators | `nc.sentiment` |

📋 **Quick copy-paste cheat:**

```yaml
# Evaluator
Kind: LLM Judge
Evaluator ID: nc.sentiment
System prompt: |
  You are a sentiment classifier. Classify only the customer message. Be strict about boundaries: NEUTRAL is the default; pick FRUSTRATED or ANGRY only when there is clear language of impatience, rudeness, or escalation. Reply with valid JSON only.
Description: Categorical sentiment of the user's message (NEUTRAL / POSITIVE / FRUSTRATED / ANGRY).
Output key: sentiment
Output type: string
Pass when: leave blank — this is categorical, dashboard charts the breakdown
User prompt: |
  Classify the emotional state expressed in this customer message.
  
  Message: {{latest_user_message}}
  
  Categories:
  - NEUTRAL: standard product question, no emotion
  - POSITIVE: enthusiastic, complimentary
  - FRUSTRATED: showing impatience, repeating themselves
  - ANGRY: rude language, demanding human, threatening to leave
  
  Reply JSON only: {"sentiment": "<category>", "confidence": <0.0-1.0>, "trigger_phrases": [...]}

# Rule
Rule ID: online.nc.sentiment
Selector: User-visible turn
Sample rate: 25
Evaluators: nc.sentiment
```

---

### 8. JSON-response validity (JSON Schema, pass/fail)

**Why it matters:** some prompts ask the AI to return JSON. Catches formatting drift without needing an LLM judge — pure schema validation, free.

| Field | Value |
|---|---|
| Kind | `JSON Schema` |
| Evaluator ID | `json.valid` |
| Description | `True if the assistant response is valid JSON.` |
| Evaluate against | `Response` |
| Schema | `{}` *(empty schema accepts any well-formed JSON)* |
| Output key | `json_valid` |
| Output type | `bool` |
| Pass when | `true` |

**Matching Rule:**

| Field | Value |
|---|---|
| Rule ID | `online.json.valid` |
| Selector | `User-visible turn` |
| Match criteria | `gen_ai.agent.name =~ "nc-.*|sb-.*"` |
| Sample rate | `100 (free) |
| Evaluators | `json.valid` |

📋 **Quick copy-paste cheat:**

```yaml
# Evaluator
Kind: JSON Schema
Evaluator ID: json.valid
Description: True if the assistant response is valid JSON.
Evaluate against: Response
Output key: json_valid
Output type: bool
Pass when: true

# Rule
Rule ID: online.json.valid
Selector: User-visible turn
Sample rate: 100 (free)
Evaluators: json.valid
```

---

### 9. SupportBot AI usage appropriateness (LLM Judge, categorical)

**Why it matters:** chargeback story. Some employees use the bot for legitimate ops questions; some use it for chit-chat. This evaluator separates the two so the dashboard can show "AI wasted hours per employee."

| Field | Value |
|---|---|
| Kind | `LLM Judge` |
| Evaluator ID | `sbAiUsage` |
| Description | `Was this a worthwhile use of the SupportBot? Flag wasteful / trivial / abusive employee prompts.` |
| System prompt | *(paste below)* |
| User prompt | *(paste below)* |
| Output key | `usage` |
| Output type | `string` |

**System prompt:**
```
You are reviewing whether an Acme employee's question to the internal help bot was a productive use of AI. Be honest. Many prompts are perfectly legit; some are wasteful (could be Googled in 5s), some are abusive (chit-chat, gaming the system, irrelevant). Reply with valid JSON only — no prose outside the JSON object.
```

**User prompt:**
```
Classify the employee's use of the AI help bot.

Employee message: {{latest_user_message}}
Tools the bot would consult: {{tools}}

Categories:
- WORTHY: legitimate question that benefits from the bot's tools
- BORDERLINE: answerable via a 10-second web search; using AI is OK but inefficient
- WASTEFUL: trivial, social, or off-topic — the bot adds no value
- ABUSIVE: gaming the system, irrelevant requests, or attempts to extract data the employee shouldn't see

Reply JSON only: {"usage": "<category>", "confidence": <0.0-1.0>, "rationale": "<one sentence>"}
```

**Matching Rule:**

| Field | Value |
|---|---|
| Rule ID | `online.sb.ai_usage` |
| Selector | `User-visible turn` |
| Match criteria | `gen_ai.agent.name =~ "sb-.*"` |
| Sample rate | `15` |
| Evaluators | `sbAiUsage` |

---

### 10. NeonCart conciseness (LLM Judge, pass/fail)

**Why it matters:** rambling AI responses degrade UX. Catches verbose preambles, restated questions, and unsolicited upsells.

| Field | Value |
|---|---|
| Kind | `LLM Judge` |
| Evaluator ID | `ncConciseness` |
| Output key | `concise` |
| Output type | `bool` |
| Pass when | `true` |

**System prompt:**
```
You are a writing critic. A concise response answers the question directly without filler, recap of the question, multi-paragraph context, or excessive disclaimers. Be strict: 'Great question!' or 'Sure, I can help with that' is a fail. Reply with valid JSON only.
```

**User prompt:**
```
Is this AI response appropriately concise?

User asked: {{latest_user_message}}
AI responded: {{assistant_response}}

A response is CONCISE if:
- Answers the question directly within 1-3 sentences (or a short bullet list)
- No "Great question!" / "Sure, I can help" preamble
- No re-statement of the question
- No unsolicited follow-up suggestions or upsells
- No disclaimers ("As an AI..." / "Please note...")

Reply JSON only: {"concise": <true|false>, "padding_examples": ["<phrase>", ...]}
```

**Matching Rule:**

| Field | Value |
|---|---|
| Rule ID | `online.nc.conciseness` |
| Selector | `User-visible turn` |
| Match criteria | `gen_ai.agent.name =~ "nc-.*"` |
| Sample rate | `10` |
| Evaluators | `ncConciseness` |

---

### 11. SupportBot conciseness (LLM Judge, pass/fail)

**Why it matters:** employees want answers, not essays. Internal bot prose that's too long actually wastes more time than it saves.

| Field | Value |
|---|---|
| Kind | `LLM Judge` |
| Evaluator ID | `sbConciseness` |
| Output key | `concise` |
| Output type | `bool` |
| Pass when | `true` |

**System prompt:**
```
You are a writing critic for an internal help bot. Acme employees want direct answers, not preamble or essay-length explanations. Be strict: a response with 'I'd be happy to help!' or excessive disclaimers fails. Reply with valid JSON only.
```

**User prompt:**
```
Is this internal help bot response appropriately concise?

Employee asked: {{latest_user_message}}
Bot responded: {{assistant_response}}

A response is CONCISE if:
- Provides the answer / next action in the first sentence
- No "I'd be happy to help" / "Let me look that up" preamble
- No restating of company policy the employee already knows
- No "If you need further assistance, please..." closer

Reply JSON only: {"concise": <true|false>, "padding_examples": ["<phrase>", ...]}
```

**Matching Rule:**

| Field | Value |
|---|---|
| Rule ID | `online.sb.conciseness` |
| Selector | `User-visible turn` |
| Match criteria | `gen_ai.agent.name =~ "sb-.*"` |
| Sample rate | `10` |
| Evaluators | `sbConciseness` |

---

### 12. SupportBot brand voice (LLM Judge, pass/fail)

**Why it matters:** internal bots that talk like marketing emails feel off-brand. This evaluator flags marketing-speak ("amazing", "leverage", "you'll love") AND the inverse — generic language where Acme-specific terms should appear ("your company's HR system" instead of "Acme HR portal").

| Field | Value |
|---|---|
| Kind | `LLM Judge` |
| Evaluator ID | `sbBrandVoice` |
| Output key | `on_brand` |
| Output type | `bool` |
| Pass when | `true` |

**System prompt:**
```
You audit whether an internal help bot speaks in the right voice. It should sound like a knowledgeable Acme teammate — concrete, factual, uses internal terminology (Acme HR portal, Acme expense system, Acme runbook, etc.). It should NOT pitch / upsell / use marketing language ('amazing', 'incredible', 'leverage', 'unlock', "you'll love"). Reply with valid JSON only.
```

**User prompt:**
```
Does this internal help bot response sound like an Acme teammate, or like a marketing pitch?

Employee asked: {{latest_user_message}}
Bot responded: {{assistant_response}}

A response PASSES voice check if:
- Uses Acme-specific terminology when relevant ("Acme HR portal", "Acme expense system")
- Reads like an internal helpdesk reply: concrete, factual, action-oriented
- Does NOT pitch products, upsell features, or use marketing adjectives ("amazing", "powerful", "leverage", "unlock")
- Does NOT address the employee like a prospect ("you'll love...", "discover...", "experience...")

Reply JSON only: {"on_brand": <true|false>, "violations": ["<marketing phrase>", ...]}
```

**Matching Rule:**

| Field | Value |
|---|---|
| Rule ID | `online.sb.brand_voice` |
| Selector | `User-visible turn` |
| Match criteria | `gen_ai.agent.name =~ "sb-.*"` |
| Sample rate | `10` |
| Evaluators | `sbBrandVoice` |

---

### 13. Pirate first-mate potential (LLM Judge, 0-10) — JOKE

**Why it matters:** it doesn't. This is a gag evaluator — useful because every demo benefits from one whimsical panel that gets a laugh when a prospect notices it in the evaluator list. Sparks the "wait, what?" conversation about what evaluators CAN do (anything you can prompt for). Easy to skip via `--skip sbPirateMate`.

| Field | Value |
|---|---|
| Kind | `LLM Judge` |
| Evaluator ID | `sbPirateMate` |
| Output key | `first_mate_score` |
| Output type | `number` |
| Pass threshold | `7` |
| Min | `0` / Max | `10` |

**System prompt:**
```
You are a pirate captain evaluating employees for first-mate potential. Score honestly based ONLY on what their message reveals. Look for: boldness of question, willingness to take initiative, healthy disregard for bureaucracy, mention of swashbuckling vocabulary, sense of adventure, OR conversely — extreme corporate compliance, fear of risk, deep love of TPS reports (auto-disqualifies). Reply with valid JSON only. Yes this is a joke evaluator. Take it seriously anyway.
```

**User prompt:**
```
Score this employee's first-mate-on-a-pirate-ship potential.

Employee asked: {{latest_user_message}}

Rate 0-10 across these dimensions, then average and round:
- BOLDNESS: does the question suggest a curious, risk-tolerant mind?
- INITIATIVE: would they grab the wheel in a storm, or wait for IT to fix it?
- ANTI-BUREAUCRACY: do they sound like they enjoy the expense report form?
- SWASHBUCKLE QUOTIENT: bonus points for maritime / piratical / treasure-related vocabulary
- LOYALTY VECTOR: does their tone suggest they'd back you up against the Royal Navy?

Auto-disqualifiers (score 0): "synergy", "circling back", "let's take this offline", unironic "ROI"
Auto-promoters (bonus to 10): "treasure", "ye", "captain", "the high seas", any 'arrr'

Reply JSON only: {"first_mate_score": <0-10>, "verdict": "<one-line pirate captain's log entry>", "auto_flags": ["<flag1>", ...]}
```

**Matching Rule:**

| Field | Value |
|---|---|
| Rule ID | `online.sb.pirate_mate` |
| Selector | `User-visible turn` |
| Match criteria | `gen_ai.agent.name =~ "sb-.*"` |
| Sample rate | `5` (this is a gag — don't burn judge tokens on it) |
| Evaluators | `sbPirateMate` |

---

## Suggested rollout order

1. **#1 `nc.quality`** — broadest signal. Validates the eval pipeline end-to-end before adding more.
2. **#3 `nc.groundedness`** — the demo punchline. Visualizes "AI hallucinates products" failure per model.
3. **#2 `sb.quality`** — gives you the SupportBot half of the overall "AI health" KPI.
4. **#6 `sb.pii`** — lands the compliance beat for internal AI.
5. **#7 `nc.sentiment`** — for the "AI conversation health" panel.
6. **#8 `json.valid`** — free schema check.
7. **#4 `sb.groundedness`** — internal-bot version of #3.
8. **#5 `hallucination`** — tool-less fallback.

## How the dashboard uses evaluation results

Sigil exposes evaluation results as Prometheus metrics. Add panels with:

```promql
# Pass rate per evaluator, per model — last hour
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

Drop into a Stat panel grouped by `evaluator`, color thresholds at 80% and 95%. Tells the side-by-side "which model is best at X" story.

For PII / hallucination — invert (higher = worse): `count by (...) (sigil_eval_executions_total{status="fail",evaluator="sb.pii"})`.

## Cost gotcha

LLM-judge evaluators run every conversation through a second LLM call. At default loadgen volume (~3-5 conversations/min) and Haiku judge pricing:

- 100% sample rate per evaluator ≈ $5-10/day
- 10% sample rate per evaluator ≈ $0.50-1/day

Use Haiku as judge — never Opus. Regex / JSON Schema / Heuristic kinds have zero per-call cost — safe at 100%.

## Where the UI lives

```
Grafana → Apps → AI Observability → Evaluation
  → Overview     dashboard of all eval activity
  → Results      browse individual evaluation outcomes
  → Evaluators   create / edit evaluators (this doc walks through these)
  → Rules        wire evaluators to traffic slices (filter + sample rate)
  → Guards       block requests at gateway based on eval verdicts (advanced)
```

The 8 evaluators above set up Evaluators + Rules. Guards (real-time blocking based on eval verdicts) is a separate setup — out of scope for the initial demo.
