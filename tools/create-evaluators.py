#!/usr/bin/env python3
"""Create all 18 Sigil evaluators (one is a joke — sbPirateMate) for the ai-o11y-demo-apps demo via API.

Hits POST {GRAFANA_URL}/api/plugins/grafana-sigil-app/resources/eval/evaluators
for each evaluator. Uses Bearer auth (Grafana service-account token).

Usage:
    export GRAFANA_URL=https://YOUR-STACK.grafana.net
    export GRAFANA_API_TOKEN=glsa_xxxxxxxx
    python3 tools/create-evaluators.py

Optional flags:
    --judge-provider PROVIDER   override default judge provider (e.g. anthropic, anthropic-vertex)
    --judge-model MODEL         override default judge model (e.g. claude-haiku-4-5-20251001)
    --skip ID [ID ...]          skip specific evaluator IDs
    --only ID [ID ...]          create only the listed IDs

Exits non-zero if any POST fails.
"""
from __future__ import annotations
import argparse, json, os, sys, urllib.request, urllib.error
from datetime import date

VERSION = date.today().isoformat()

# Default judge target — override with flags. Sigil's "Default" UI value maps
# to whatever the cluster has wired up; spelling these out keeps the script
# reproducible across stacks.
DEFAULT_JUDGE_PROVIDER = "anthropic"
DEFAULT_JUDGE_MODEL = "claude-haiku-4-5-20251001"

# ── Evaluator definitions ────────────────────────────────────────────────────
# Each entry maps 1:1 to the Sigil Create-evaluator POST body.

def llm_judge(eid, description, system_prompt, user_prompt,
              output_keys, max_tokens=256, temperature=0,
              pass_threshold=None, min_value=None, max_value=None):
    out = {
        "evaluator_id": eid,
        "version": VERSION,
        "kind": "llm_judge",
        "description": description,
        "config": {
            "provider": "{{JUDGE_PROVIDER}}",
            "model": "{{JUDGE_MODEL}}",
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
        "output_keys": output_keys,
    }
    if pass_threshold is not None: out["pass_threshold"] = pass_threshold
    if min_value is not None: out["min"] = min_value
    if max_value is not None: out["max"] = max_value
    return out


def regex_eval(eid, description, pattern):
    return {
        "evaluator_id": eid,
        "version": VERSION,
        "kind": "regex",
        "description": description,
        "config": {"pattern": pattern, "evaluate_against": "response"},
        "output_keys": [{"key": "regex_match", "type": "bool", "pass_value": False}],
    }


def json_schema_eval(eid, description, schema):
    return {
        "evaluator_id": eid,
        "version": VERSION,
        "kind": "json_schema",
        "description": description,
        "config": {"schema": schema, "evaluate_against": "response"},
        "output_keys": [{"key": "json_valid", "type": "bool", "pass_value": True}],
    }


def heuristic_eval(eid, description, rule_tree, output_key="heuristic_pass"):
    return {
        "evaluator_id": eid,
        "version": VERSION,
        "kind": "heuristic",
        "description": description,
        "config": {"version": "1", **rule_tree},
        "output_keys": [{"key": output_key, "type": "bool", "pass_value": True}],
    }


EVALUATORS = [
    # 1. NeonCart response quality
    llm_judge(
        eid="ncQuality",
        description="0-5 quality score for nc-chatbot and nc-gift-finder responses (relevance, completeness, accuracy, tone).",
        system_prompt=(
            "You evaluate one assistant response. Use only the user input "
            "and assistant output. Follow the score field description exactly. "
            "Be strict. If uncertain, choose the lower score."
        ),
        user_prompt=(
            "You are evaluating an AI shopping assistant's response quality.\n\n"
            "User asked: {{latest_user_message}}\n"
            "AI responded: {{assistant_response}}\n"
            "Tools used: {{tool_calls}}\n\n"
            "Rate 0-5 on:\n"
            "- RELEVANCE: did it address what the user asked?\n"
            "- COMPLETENESS: enough info to act on?\n"
            "- ACCURACY: are product details / prices / availability correct?\n"
            "- TONE: helpful, not pushy?\n\n"
            'Reply JSON only: {"score": <0.0-5.0>, "rationale": "<one sentence>"}'
        ),
        output_keys=[{"key": "score", "type": "number"}],
        pass_threshold=3.0, min_value=0, max_value=5,
        max_tokens=256,
    ),
    # 2. SupportBot response quality
    llm_judge(
        eid="sbQuality",
        description="0-5 quality score for sb-* agent responses (actionable, policy-aligned, complete, professional tone).",
        system_prompt=(
            "You evaluate one assistant response. Use only the user input "
            "and assistant output. Follow the score field description exactly. "
            "Be strict. If uncertain, choose the lower score."
        ),
        user_prompt=(
            "You are evaluating an internal employee help bot's response.\n\n"
            "Employee asked: {{latest_user_message}}\n"
            "Bot responded: {{assistant_response}}\n"
            "Tools used: {{tool_calls}}\n\n"
            "Rate 0-5:\n"
            "- ACTIONABLE: did it tell the employee what to do, or just describe the situation?\n"
            "- POLICY-ALIGNED: does the advice match company policy as referenced in tool outputs?\n"
            "- COMPLETENESS: would the employee need to ask a follow-up to act?\n"
            "- TONE: professional, not condescending, no excessive disclaimers?\n\n"
            'Reply JSON only: {"score": <0.0-5.0>, "rationale": "<one sentence>"}'
        ),
        output_keys=[{"key": "score", "type": "number"}],
        pass_threshold=3.0, min_value=0, max_value=5,
        max_tokens=256,
    ),
    # 3. NeonCart groundedness
    llm_judge(
        eid="ncGroundedness",
        description="Boolean: did the NC chatbot/gift-finder use only catalog data returned by its tools, or did it hallucinate products?",
        system_prompt=(
            "You verify whether an AI response is grounded in tool data only. "
            "Be strict: if a product SKU, price, spec, or availability claim does "
            "not appear VERBATIM in the tool results, mark it as ungrounded. "
            "Do not give the response benefit of the doubt. Reply with valid "
            "JSON only — no prose outside the JSON object."
        ),
        user_prompt=(
            "You are verifying whether an AI shopping assistant's response is grounded\n"
            "in the tool data it received.\n\n"
            "Tool results: {{tool_results}}\n"
            "AI response: {{assistant_response}}\n\n"
            "A grounded response only mentions products / prices / specs that appear\n"
            "in the tool results above. Inventing SKUs, prices, descriptions, or\n"
            "availability NOT in the tool output = NOT grounded.\n\n"
            'Reply JSON only: {"grounded": <true|false>, "ungrounded_claims": ["<claim 1>", ...]}'
        ),
        output_keys=[{"key": "grounded", "type": "bool", "pass_value": True}],
        max_tokens=300,
    ),
    # 4. SupportBot groundedness
    llm_judge(
        eid="sbGroundedness",
        description="Boolean: did the SB specialist use only data returned by its tools, or did it invent policy/details?",
        system_prompt=(
            "You verify whether an internal help bot grounded its answer in tool data only. "
            "Be strict: if a runbook step, expense amount, account detail, or policy claim "
            "does not appear VERBATIM in the tool output, mark it as ungrounded. "
            "Compliance-critical — err on the strict side. Reply with valid JSON only."
        ),
        user_prompt=(
            "You are verifying an internal help bot grounded its answer in tool data.\n\n"
            "Tools called: {{tool_calls}}\n"
            "Tool results: {{tool_results}}\n"
            "Bot response: {{assistant_response}}\n\n"
            "If the bot cited a runbook step, expense amount, account detail, or policy\n"
            "NOT present in the tool output, mark as NOT grounded.\n\n"
            'Reply JSON only: {"grounded": <true|false>, "ungrounded_claims": [...]}'
        ),
        output_keys=[{"key": "grounded", "type": "bool", "pass_value": True}],
        max_tokens=300,
    ),
    # 5. Hallucination
    llm_judge(
        eid="hallucination",
        description="Boolean: did the AI response invent facts, contradict known information, or fabricate identifiers?",
        system_prompt=(
            "You are a fact-checker. Flag any claim in the AI response that is "
            "fabricated, contradicts widely-known facts, or contains specific "
            "identifiers (SKUs, dollar amounts, dates) that look invented rather "
            "than retrieved. Err on the side of flagging. Reply with valid JSON only."
        ),
        user_prompt=(
            "Does this AI response contain any factual claim that:\n"
            "- is fabricated (made up)\n"
            "- contradicts widely known facts\n"
            "- mentions specific identifiers (SKUs, dollar amounts, dates) that look\n"
            "  invented rather than retrieved?\n\n"
            "Prompt: {{latest_user_message}}\n"
            "Response: {{assistant_response}}\n\n"
            'Reply JSON only: {"hallucination": <true|false>, "examples": [...]}'
        ),
        output_keys=[{"key": "hallucination", "type": "bool", "pass_value": False}],
        max_tokens=300,
    ),
    # 6a. PII regex evaluators
    regex_eval(
        eid="piiSsn",
        description="Matches a US Social Security Number in the format NNN-NN-NNNN.",
        pattern=r"\b\d{3}-\d{2}-\d{4}\b",
    ),
    regex_eval(
        eid="piiCreditCard",
        description="Matches a 13-16 digit credit card number with optional spaces or dashes.",
        pattern=r"\b(?:\d[ -]*?){13,16}\b",
    ),
    regex_eval(
        eid="piiEmail",
        description="Matches an email address.",
        pattern=r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    ),
    regex_eval(
        eid="piiPhone",
        description="Matches a US phone number with or without country code.",
        pattern=r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
    ),
    regex_eval(
        eid="piiIp",
        description="Matches an IPv4 address.",
        pattern=r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    ),
    # 6b. PII heuristic — combines the 5 regex results
    heuristic_eval(
        eid="sbPii",
        description="Pass if NONE of the PII regex evaluators matched the response.",
        rule_tree={
            "combinator": "all_of",
            "rules": [
                {"evaluator_id": "piiSsn", "condition": "is_not_match"},
                {"evaluator_id": "piiCreditCard", "condition": "is_not_match"},
                {"evaluator_id": "piiEmail", "condition": "is_not_match"},
                {"evaluator_id": "piiPhone", "condition": "is_not_match"},
                {"evaluator_id": "piiIp", "condition": "is_not_match"},
            ],
        },
    ),
    # 7. NeonCart angry-customer detection
    llm_judge(
        eid="ncSentiment",
        description="Categorical sentiment of the user's message (NEUTRAL / POSITIVE / FRUSTRATED / ANGRY).",
        system_prompt=(
            "You are a sentiment classifier. Classify only the customer message. "
            "Be strict about boundaries: NEUTRAL is the default; pick FRUSTRATED "
            "or ANGRY only when there is clear language of impatience, rudeness, "
            "or escalation. Reply with valid JSON only."
        ),
        user_prompt=(
            "Classify the emotional state expressed in this customer message.\n\n"
            "Message: {{latest_user_message}}\n\n"
            "Categories:\n"
            "- NEUTRAL: standard product question, no emotion\n"
            "- POSITIVE: enthusiastic, complimentary\n"
            "- FRUSTRATED: showing impatience, repeating themselves\n"
            "- ANGRY: rude language, demanding human, threatening to leave\n\n"
            'Reply JSON only: {"sentiment": "<category>", "confidence": <0.0-1.0>, "trigger_phrases": [...]}'
        ),
        output_keys=[{"key": "sentiment", "type": "string"}],
        max_tokens=256,
    ),
    # 7b. Conciseness — NeonCart
    llm_judge(
        eid="ncConciseness",
        description="Boolean: was the NC chatbot/gift-finder response concise and on-point (no preamble, no fluff)?",
        system_prompt=(
            "You are a writing critic. A concise response answers the question "
            "directly without filler, recap of the question, multi-paragraph "
            "context, or excessive disclaimers. Be strict: 'Great question!' "
            "or 'Sure, I can help with that' is a fail. Reply with valid JSON only."
        ),
        user_prompt=(
            "Is this AI response appropriately concise?\n\n"
            "User asked: {{latest_user_message}}\n"
            "AI responded: {{assistant_response}}\n\n"
            "A response is CONCISE if:\n"
            "- Answers the question directly within 1-3 sentences (or a short bullet list)\n"
            "- No 'Great question!' / 'Sure, I can help' preamble\n"
            "- No re-statement of the question\n"
            "- No unsolicited follow-up suggestions or upsells\n"
            "- No disclaimers ('As an AI...' / 'Please note...')\n\n"
            'Reply JSON only: {"concise": <true|false>, "padding_examples": ["<phrase>", ...]}'
        ),
        output_keys=[{"key": "concise", "type": "bool", "pass_value": True}],
        max_tokens=256,
    ),
    # 7c. Conciseness — SupportBot
    llm_judge(
        eid="sbConciseness",
        description="Boolean: was the SB specialist response concise (employees want answers, not essays)?",
        system_prompt=(
            "You are a writing critic for an internal help bot. Acme employees want "
            "direct answers, not preamble or essay-length explanations. Be strict: "
            "a response with 'I'd be happy to help!' or excessive disclaimers fails. "
            "Reply with valid JSON only."
        ),
        user_prompt=(
            "Is this internal help bot response appropriately concise?\n\n"
            "Employee asked: {{latest_user_message}}\n"
            "Bot responded: {{assistant_response}}\n\n"
            "A response is CONCISE if:\n"
            "- Provides the answer / next action in the first sentence\n"
            "- No 'I'd be happy to help' / 'Let me look that up' preamble\n"
            "- No restating of company policy the employee already knows\n"
            "- No 'If you need further assistance, please...' closer\n\n"
            'Reply JSON only: {"concise": <true|false>, "padding_examples": ["<phrase>", ...]}'
        ),
        output_keys=[{"key": "concise", "type": "bool", "pass_value": True}],
        max_tokens=256,
    ),
    # 7d. AI usage appropriateness — was the employee's prompt a worthwhile use of the bot?
    llm_judge(
        eid="sbAiUsage",
        description="Was this a worthwhile use of the SupportBot? Flag wasteful / trivial / abusive employee prompts.",
        system_prompt=(
            "You are reviewing whether an Acme employee's question to the internal "
            "help bot was a productive use of AI. Be honest. Many prompts are perfectly "
            "legit; some are wasteful (could be Googled in 5s), some are abusive "
            "(chit-chat, gaming the system, irrelevant). Reply with valid JSON only "
            "— no prose outside the JSON object."
        ),
        user_prompt=(
            "Classify the employee's use of the AI help bot.\n\n"
            "Employee message: {{latest_user_message}}\n"
            "Tools the bot would consult: {{tools}}\n\n"
            "Categories:\n"
            "- WORTHY: legitimate question that benefits from the bot's tools (runbooks, expense lookup, account info, internal policy)\n"
            "- BORDERLINE: answerable via a 10-second web search or existing docs; using AI is OK but inefficient\n"
            "- WASTEFUL: trivial, social, or off-topic — the bot adds no value\n"
            "- ABUSIVE: gaming the system, irrelevant requests, or attempts to extract data the employee shouldn't see\n\n"
            'Reply JSON only: {"usage": "<category>", "confidence": <0.0-1.0>, "rationale": "<one sentence>"}'
        ),
        output_keys=[{"key": "usage", "type": "string"}],
        max_tokens=256,
    ),

    # 7e. Brand voice — does the bot sound like an Acme teammate, not a sales rep?
    llm_judge(
        eid="sbBrandVoice",
        description="Boolean: does the SB specialist speak like an internal teammate using Acme terminology, NOT a sales rep pitching the employee?",
        system_prompt=(
            "You audit whether an internal help bot speaks in the right voice. "
            "It should sound like a knowledgeable Acme teammate — concrete, factual, "
            "uses internal terminology (Acme HR portal, Acme expense system, Acme "
            "runbook, etc.). It should NOT pitch / upsell / use marketing language "
            "('amazing', 'incredible', 'leverage', 'unlock', \"you'll love\"). "
            "Reply with valid JSON only."
        ),
        user_prompt=(
            "Does this internal help bot response sound like an Acme teammate, or like a marketing pitch?\n\n"
            "Employee asked: {{latest_user_message}}\n"
            "Bot responded: {{assistant_response}}\n\n"
            "A response PASSES voice check if:\n"
            "- Uses Acme-specific terminology when relevant (e.g. 'Acme HR portal', 'Acme expense system') instead of generic phrases\n"
            "- Reads like an internal helpdesk reply: concrete, factual, action-oriented\n"
            "- Does NOT pitch products, upsell features, or use marketing adjectives ('amazing', 'powerful', 'robust', 'leverage', 'unlock', 'best-in-class')\n"
            "- Does NOT address the employee like a prospect (\"you'll love...\", 'discover...', 'experience...')\n\n"
            'Reply JSON only: {"on_brand": <true|false>, "violations": ["<marketing phrase or generic substitute>", ...]}'
        ),
        output_keys=[{"key": "on_brand", "type": "bool", "pass_value": True}],
        max_tokens=300,
    ),

    # 12b. [Demo gag] Pirate first-mate evaluator
    #      Yes this is a joke. Provided because demos benefit from one whimsical
    #      panel in the eval dashboard — sparks conversation when prospects see
    #      the eval list. Easy to skip via --skip sbPirateMate.
    llm_judge(
        eid="sbPirateMate",
        description="[Demo gag] 0-10 score: how likely is this Acme employee to abandon their cubicle and join you as first mate on a pirate ship?",
        system_prompt=(
            "You are a pirate captain evaluating employees for first-mate potential. "
            "Score honestly based ONLY on what their message reveals. Look for: boldness "
            "of question, willingness to take initiative, healthy disregard for "
            "bureaucracy, mention of swashbuckling vocabulary, sense of adventure, OR "
            "conversely — extreme corporate compliance, fear of risk, deep love of TPS "
            "reports (auto-disqualifies). Reply with valid JSON only. Yes this is a joke "
            "evaluator. Take it seriously anyway."
        ),
        user_prompt=(
            "Score this employee's first-mate-on-a-pirate-ship potential.\n\n"
            "Employee asked: {{latest_user_message}}\n\n"
            "Rate 0-10 across these dimensions, then average and round:\n"
            "- BOLDNESS: does the question suggest a curious, risk-tolerant mind?\n"
            "- INITIATIVE: would they grab the wheel in a storm, or wait for IT?\n"
            "- ANTI-BUREAUCRACY: do they sound like they enjoy the expense report form?\n"
            "- SWASHBUCKLE QUOTIENT: bonus points for maritime / piratical vocabulary\n"
            "- LOYALTY VECTOR: would they back you up against the Royal Navy?\n\n"
            "Auto-disqualifiers (score 0): 'synergy', 'circling back', 'let's take this offline'\n"
            "Auto-promoters (bonus to 10): 'treasure', 'ye', 'captain', 'arrr'\n\n"
            'Reply JSON only: {"first_mate_score": <0-10>, "verdict": "<pirate captain\'s log entry>", "auto_flags": [...]}'
        ),
        output_keys=[{"key": "first_mate_score", "type": "number"}],
        pass_threshold=7, min_value=0, max_value=10,
        max_tokens=250,
    ),

    # 13. JSON schema validity
    json_schema_eval(
        eid="jsonValid",
        description="True if the assistant response is valid JSON.",
        schema={},
    ),
]


# ── HTTP plumbing ────────────────────────────────────────────────────────────

def post_evaluator(base_url, token, evaluator):
    url = f"{base_url.rstrip('/')}/api/plugins/grafana-sigil-app/resources/eval/evaluators"
    body = json.dumps(evaluator).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode()[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:500]
    except Exception as e:
        return 0, str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge-provider", default=DEFAULT_JUDGE_PROVIDER)
    ap.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    ap.add_argument("--skip", nargs="*", default=[])
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--dry-run", action="store_true", help="Print payloads without POSTing")
    args = ap.parse_args()

    base_url = os.environ.get("GRAFANA_URL", "").rstrip("/")
    token = os.environ.get("GRAFANA_API_TOKEN", "")
    if not args.dry_run:
        if not base_url or not token:
            sys.exit("Set GRAFANA_URL + GRAFANA_API_TOKEN (or use --dry-run)")

    # Substitute the judge target placeholders in all LLM-judge configs
    for e in EVALUATORS:
        if e["kind"] == "llm_judge":
            e["config"]["provider"] = args.judge_provider
            e["config"]["model"] = args.judge_model

    # Filter
    todo = EVALUATORS
    if args.only:
        todo = [e for e in todo if e["evaluator_id"] in args.only]
    todo = [e for e in todo if e["evaluator_id"] not in args.skip]

    print(f"Creating {len(todo)} evaluator(s) on {base_url or '(dry-run)'}")
    print(f"  judge target: {args.judge_provider} / {args.judge_model}")
    print()

    failed = []
    for e in todo:
        if args.dry_run:
            print(f"→ {e['evaluator_id']} ({e['kind']})  payload:")
            print(json.dumps(e, indent=2))
            print()
            continue
        status, msg = post_evaluator(base_url, token, e)
        ok = 200 <= status < 300
        marker = "✓" if ok else "✗"
        print(f"  {marker} {e['evaluator_id']:20s}  {e['kind']:13s}  HTTP {status}")
        if not ok:
            print(f"      {msg}")
            failed.append(e["evaluator_id"])

    if failed:
        print(f"\nFailed: {failed}")
        sys.exit(1)
    if not args.dry_run:
        print(f"\nDone. Next: create Rules in the Sigil UI to wire each evaluator to its target traffic.")
        print("See docs/EVALS.md for the matching Rule entries per evaluator.")


if __name__ == "__main__":
    main()
