// Paste into your Grafana DevTools Console while logged in.
// Creates Sigil eval rules that wire the 18 evaluators (from create-evaluators.js)
// to their target traffic slices.
//
// Endpoint: POST {origin}/api/plugins/grafana-sigil-app/resources/eval/rules
// Schema (confirmed from a live capture):
//   { rule_id, enabled, selector, match: {key: value}, sample_rate: 0-1, evaluator_ids[] }
//
// Run AFTER create-evaluators.js — rules reference evaluator IDs.
//
// One-liner (always fresh):
//   fetch('https://raw.githubusercontent.com/stephenwagner-grafana/ai-o11y-demo-apps/main/tools/create-rules.js?cb='+Date.now()).then(r=>r.text()).then(eval)

(async () => {
  const URL = `${window.location.origin}/api/plugins/grafana-sigil-app/resources/eval/rules`;

  // ── Helper ──────────────────────────────────────────────────────────────────
  // match takes exact key-value pairs (no regex). For evaluators that should
  // span multiple agents, we emit one rule per agent.
  // Sigil rule IDs only accept letters/digits/_/. — sanitize hyphens to underscores.
  const sanitize = s => s.replace(/-/g, "_");
  const rule = (id, evaluators, agentName, sampleRate, selector = "user_visible_turn") => ({
    rule_id: sanitize(id),
    enabled: true,
    selector,
    match: { "tags.gen_ai.agent.name": agentName },
    sample_rate: sampleRate,   // decimal 0-1, NOT percent
    evaluator_ids: evaluators,
  });

  // Build the rule set. Evaluators targeting multiple agents get one rule per agent.
  const NC_AGENTS = ["nc-chatbot", "nc-gift-finder"];
  const SB_USER_FACING = ["sb-router", "sb-billing", "sb-tech-support", "sb-account-management"];
  const SB_PII_RISK = ["sb-account-management", "sb-billing"];

  const RULES = [];

  // 1. ncQuality — both NC agents, 10% sample
  NC_AGENTS.forEach(a => RULES.push(rule(`online.nc.quality.${a}`,        ["ncQuality"],       a, 0.10)));
  // 2. sbQuality — all SB agents, 10% sample
  SB_USER_FACING.forEach(a => RULES.push(rule(`online.sb.quality.${a}`,   ["sbQuality"],       a, 0.10)));
  // 3. ncGroundedness — chatbot + gift-finder
  NC_AGENTS.forEach(a => RULES.push(rule(`online.nc.groundedness.${a}`,   ["ncGroundedness"],  a, 0.15)));
  // 4. sbGroundedness — billing + tech-support + account-mgmt (excl. router)
  ["sb-billing", "sb-tech-support", "sb-account-management"].forEach(a =>
    RULES.push(rule(`online.sb.groundedness.${a}`,                         ["sbGroundedness"],  a, 0.15)));
  // 5. hallucination — broad, low sample
  [...NC_AGENTS, ...SB_USER_FACING].forEach(a =>
    RULES.push(rule(`online.hallucination.${a}`,                           ["hallucination"],   a, 0.05)));
  // 6. sbPii — high sample on PII-risk agents
  SB_PII_RISK.forEach(a => RULES.push(rule(`online.sb.pii.${a}`,           ["sbPii"],           a, 1.00)));
  // 7. ncSentiment — both NC agents
  NC_AGENTS.forEach(a => RULES.push(rule(`online.nc.sentiment.${a}`,       ["ncSentiment"],     a, 0.25)));
  // 8. jsonValid — every agent, free (no LLM call)
  [...NC_AGENTS, ...SB_USER_FACING].forEach(a =>
    RULES.push(rule(`online.json.valid.${a}`,                              ["jsonValid"],       a, 1.00)));
  // 9. sbAiUsage — all SB agents
  SB_USER_FACING.forEach(a => RULES.push(rule(`online.sb.ai_usage.${a}`,   ["sbAiUsage"],       a, 0.15)));
  // 10. ncConciseness
  NC_AGENTS.forEach(a => RULES.push(rule(`online.nc.conciseness.${a}`,     ["ncConciseness"],   a, 0.10)));
  // 11. sbConciseness
  SB_USER_FACING.forEach(a => RULES.push(rule(`online.sb.conciseness.${a}`,["sbConciseness"],   a, 0.10)));
  // 12. sbBrandVoice
  SB_USER_FACING.forEach(a => RULES.push(rule(`online.sb.brand_voice.${a}`,["sbBrandVoice"],    a, 0.10)));
  // 13. sbPirateMate — the gag, 5% on all SB
  SB_USER_FACING.forEach(a => RULES.push(rule(`online.sb.pirate_mate.${a}`,["sbPirateMate"],    a, 0.05)));

  console.log(`%cCreating ${RULES.length} rules on ${window.location.origin}`,
              "font-weight: bold; color: #00f0ff;");

  const results = { ok: [], skipped: [], fail: [] };
  for (const r of RULES) {
    try {
      const resp = await fetch(URL, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify(r),
      });
      const text = await resp.text();
      if (resp.ok) {
        console.log(`%c  ✓ ${r.rule_id.padEnd(45)} → ${r.evaluator_ids.join(",")} HTTP ${resp.status}`,
                    "color: #39ff7e;");
        results.ok.push(r.rule_id);
      } else if (resp.status === 409) {
        // Already exists — silent skip
        results.skipped.push(r.rule_id);
      } else {
        console.log(`%c  ✗ ${r.rule_id.padEnd(45)} HTTP ${resp.status}`,
                    "color: #ff3b6b;");
        console.log(`      ${text.slice(0, 300)}`);
        results.fail.push({ id: r.rule_id, status: resp.status, body: text });
      }
    } catch (e) {
      console.log(`%c  ✗ ${r.rule_id} threw: ${e.message}`, "color: #ff3b6b;");
      results.fail.push({ id: r.rule_id, error: e.message });
    }
  }

  console.log(`\n%c${results.ok.length} created, ${results.skipped.length} already-existed, ${results.fail.length} failed`,
              "font-weight: bold; color: #b537ff;");
  if (results.fail.length) console.table(results.fail);
  return results;
})();
