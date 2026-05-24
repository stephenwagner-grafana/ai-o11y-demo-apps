// Paste into your Grafana DevTools Console while logged in.
// Creates Sigil eval rules that wire the 18 evaluators (from create-evaluators.js)
// to per-agent traffic slices.
//
// Endpoint: POST   {origin}/api/plugins/grafana-sigil-app/resources/eval/rules
//           DELETE {origin}/api/plugins/grafana-sigil-app/resources/eval/rules/{rule_id}
//
// Match shape (captured from the UI's PATCH payload):
//   { enabled, selector, match: { agent_name: "<agent>" }, sample_rate, evaluator_ids, alert_rule_uids: [] }
//
// IMPORTANT: "agent_name" is a TOP-LEVEL match key, NOT a tag. The earlier
// `tags.gen_ai.agent.name` attempts failed because the gateway's tags dict
// (gateway/app/providers/anthropic.py:327) doesn't include agent name —
// it's passed as a separate Sigil SDK parameter and surfaces in the API
// as its own match dimension.
//
// One-liner (always fresh):
//   fetch('https://raw.githubusercontent.com/stephenwagner-grafana/ai-o11y-demo-apps/main/tools/create-rules.js?cb='+Date.now()).then(r=>r.text()).then(eval)

(async () => {
  const URL = `${window.location.origin}/api/plugins/grafana-sigil-app/resources/eval/rules`;

  // ── Cleanup: nuke everything we've ever shipped. Safe to re-run — 404s
  // are silently counted as "already gone".
  const STALE_IDS = [
    // Per-app interim
    "online.nc.quality", "online.nc.groundedness", "online.nc.sentiment",
    "online.nc.conciseness", "online.sb.quality", "online.sb.groundedness",
    "online.sb.pii", "online.sb.ai_usage", "online.sb.conciseness",
    "online.sb.brand_voice", "online.sb.pirate_mate",
    "online.nc.hallucination", "online.sb.hallucination",
    "online.nc.json_valid", "online.sb.json_valid",
    // Per-agent rules with the wrong (Tag) match shape
    "online.nc.quality.nc_chatbot", "online.nc.quality.nc_gift_finder",
    "online.sb.quality.sb_router", "online.sb.quality.sb_billing",
    "online.sb.quality.sb_tech_support", "online.sb.quality.sb_account_management",
    "online.nc.groundedness.nc_chatbot", "online.nc.groundedness.nc_gift_finder",
    "online.sb.groundedness.sb_billing", "online.sb.groundedness.sb_tech_support",
    "online.sb.groundedness.sb_account_management",
    "online.hallucination.nc_chatbot", "online.hallucination.nc_gift_finder",
    "online.hallucination.sb_router", "online.hallucination.sb_billing",
    "online.hallucination.sb_tech_support", "online.hallucination.sb_account_management",
    "online.sb.pii.sb_account_management", "online.sb.pii.sb_billing",
    "online.nc.sentiment.nc_chatbot", "online.nc.sentiment.nc_gift_finder",
    "online.json.valid.nc_chatbot", "online.json.valid.nc_gift_finder",
    "online.json.valid.sb_router", "online.json.valid.sb_billing",
    "online.json.valid.sb_tech_support", "online.json.valid.sb_account_management",
    "online.sb.ai_usage.sb_router", "online.sb.ai_usage.sb_billing",
    "online.sb.ai_usage.sb_tech_support", "online.sb.ai_usage.sb_account_management",
    "online.nc.conciseness.nc_chatbot", "online.nc.conciseness.nc_gift_finder",
    "online.sb.conciseness.sb_router", "online.sb.conciseness.sb_billing",
    "online.sb.conciseness.sb_tech_support", "online.sb.conciseness.sb_account_management",
    "online.sb.brand_voice.sb_router", "online.sb.brand_voice.sb_billing",
    "online.sb.brand_voice.sb_tech_support", "online.sb.brand_voice.sb_account_management",
    "online.sb.pirate_mate.sb_router", "online.sb.pirate_mate.sb_billing",
    "online.sb.pirate_mate.sb_tech_support", "online.sb.pirate_mate.sb_account_management",
  ];

  console.log(`%cDeleting ${STALE_IDS.length} prior rule IDs…`,
              "font-weight: bold; color: #ff9933;");
  let deleted = 0, missing = 0;
  for (const id of STALE_IDS) {
    try {
      const resp = await fetch(`${URL}/${encodeURIComponent(id)}`,
        { method: "DELETE", credentials: "include" });
      if (resp.ok) { deleted++; }
      else if (resp.status === 404) { missing++; }
      else { console.log(`  ? ${id} HTTP ${resp.status}`); }
    } catch (e) {
      console.log(`  ? ${id} threw: ${e.message}`);
    }
  }
  console.log(`%c  deleted ${deleted}, ${missing} already gone`,
              "color: #ff9933;");

  // ── Helper ──────────────────────────────────────────────────────────────────
  // match: {agent_name: "<agent>"} — UI renders this as "Agent name" criteria.
  // rule_id must be [A-Za-z0-9_.] — sanitize hyphens to underscores.
  const sanitize = s => s.replace(/-/g, "_");
  const rule = (id, evaluators, agentName, sampleRate, selector = "user_visible_turn") => ({
    rule_id: sanitize(id),
    enabled: true,
    selector,
    match: { agent_name: agentName },
    sample_rate: sampleRate,
    evaluator_ids: evaluators,
    alert_rule_uids: [],
  });

  const NC_AGENTS = ["nc-chatbot", "nc-gift-finder"];
  const SB_USER_FACING = ["sb-router", "sb-billing", "sb-tech-support", "sb-account-management"];
  const SB_PII_RISK = ["sb-account-management", "sb-billing"];

  const RULES = [];
  // 1. ncQuality
  NC_AGENTS.forEach(a => RULES.push(rule(`online.nc.quality.${a}`,        ["ncQuality"],       a, 0.10)));
  // 2. sbQuality
  SB_USER_FACING.forEach(a => RULES.push(rule(`online.sb.quality.${a}`,   ["sbQuality"],       a, 0.10)));
  // 3. ncGroundedness
  NC_AGENTS.forEach(a => RULES.push(rule(`online.nc.groundedness.${a}`,   ["ncGroundedness"],  a, 0.15)));
  // 4. sbGroundedness (excl. router)
  ["sb-billing", "sb-tech-support", "sb-account-management"].forEach(a =>
    RULES.push(rule(`online.sb.groundedness.${a}`,                         ["sbGroundedness"],  a, 0.15)));
  // 5. hallucination
  [...NC_AGENTS, ...SB_USER_FACING].forEach(a =>
    RULES.push(rule(`online.hallucination.${a}`,                           ["hallucination"],   a, 0.05)));
  // 6. sbPii
  SB_PII_RISK.forEach(a => RULES.push(rule(`online.sb.pii.${a}`,           ["sbPii"],           a, 1.00)));
  // 7. ncSentiment
  NC_AGENTS.forEach(a => RULES.push(rule(`online.nc.sentiment.${a}`,       ["ncSentiment"],     a, 0.25)));
  // 8. jsonValid
  [...NC_AGENTS, ...SB_USER_FACING].forEach(a =>
    RULES.push(rule(`online.json.valid.${a}`,                              ["jsonValid"],       a, 1.00)));
  // 9. sbAiUsage
  SB_USER_FACING.forEach(a => RULES.push(rule(`online.sb.ai_usage.${a}`,   ["sbAiUsage"],       a, 0.15)));
  // 10. ncConciseness
  NC_AGENTS.forEach(a => RULES.push(rule(`online.nc.conciseness.${a}`,     ["ncConciseness"],   a, 0.10)));
  // 11. sbConciseness
  SB_USER_FACING.forEach(a => RULES.push(rule(`online.sb.conciseness.${a}`,["sbConciseness"],   a, 0.10)));
  // 12. sbBrandVoice
  SB_USER_FACING.forEach(a => RULES.push(rule(`online.sb.brand_voice.${a}`,["sbBrandVoice"],    a, 0.10)));
  // 13. sbPirateMate
  SB_USER_FACING.forEach(a => RULES.push(rule(`online.sb.pirate_mate.${a}`,["sbPirateMate"],    a, 0.05)));

  console.log(`%cCreating ${RULES.length} per-agent rules on ${window.location.origin}`,
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
