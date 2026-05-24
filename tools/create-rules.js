// Paste into your Grafana DevTools Console while logged in.
// Creates Sigil eval rules that wire the 18 evaluators (from create-evaluators.js)
// to per-app traffic slices (neoncart vs supportbot).
//
// Endpoint: POST   {origin}/api/plugins/grafana-sigil-app/resources/eval/rules
//           DELETE {origin}/api/plugins/grafana-sigil-app/resources/eval/rules/{rule_id}
//
// Match key: `tags.app` (one of Sigil's first-class tag suggestions). Values
// are neoncart / supportbot — set on every generation via the gateway's
// tags={"app": req.app, ...} dict (gateway/app/providers/anthropic.py:327).
//
// Why per-app and not per-agent: the gateway does NOT include
// `gen_ai.agent.name` in the Sigil tags dict, so Tag-criteria rules keyed
// on that name match zero generations. The Sigil UI has a separate
// "Agent name" criteria type that DOES match, but its API payload shape
// isn't documented yet (would need a network capture from the UI). Per-app
// matching ships today; per-agent can come later by either capturing the
// "Agent name" rule shape or by adding gen_ai.agent.name to the tags dict.
//
// The eval RESULT metric (sigil_eval_executions_total) still carries
// gen_ai_agent_name as a Prom label, so dashboards retain per-specialist
// breakdowns — only the rule scope is coarser.
//
// One-liner (always fresh):
//   fetch('https://raw.githubusercontent.com/stephenwagner-grafana/ai-o11y-demo-apps/main/tools/create-rules.js?cb='+Date.now()).then(r=>r.text()).then(eval)

(async () => {
  const URL = `${window.location.origin}/api/plugins/grafana-sigil-app/resources/eval/rules`;

  // ── Cleanup: remove every prior rule_id we've shipped (per-agent + per-app).
  // Safe to re-run — 404s on missing IDs are silently counted.
  const STALE_IDS = [
    // 45 legacy per-agent IDs (tags.gen_ai.agent.name — matched 0)
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

  console.log(`%cDeleting ${STALE_IDS.length} legacy per-agent rules…`,
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
  // Match by `tags.app` — values: neoncart / supportbot
  const rule = (id, evaluators, app, sampleRate, selector = "user_visible_turn") => ({
    rule_id: id,
    enabled: true,
    selector,
    match: { "tags.app": app },
    sample_rate: sampleRate,   // decimal 0-1, NOT percent
    evaluator_ids: evaluators,
  });

  const RULES = [
    // NeonCart-only
    rule("online.nc.quality",       ["ncQuality"],       "neoncart",   0.10),
    rule("online.nc.groundedness",  ["ncGroundedness"],  "neoncart",   0.15),
    rule("online.nc.sentiment",     ["ncSentiment"],     "neoncart",   0.25),
    rule("online.nc.conciseness",   ["ncConciseness"],   "neoncart",   0.10),
    // SupportBot-only
    rule("online.sb.quality",       ["sbQuality"],       "supportbot", 0.10),
    rule("online.sb.groundedness",  ["sbGroundedness"],  "supportbot", 0.15),
    rule("online.sb.pii",           ["sbPii"],           "supportbot", 1.00),
    rule("online.sb.ai_usage",      ["sbAiUsage"],       "supportbot", 0.15),
    rule("online.sb.conciseness",   ["sbConciseness"],   "supportbot", 0.10),
    rule("online.sb.brand_voice",   ["sbBrandVoice"],    "supportbot", 0.10),
    rule("online.sb.pirate_mate",   ["sbPirateMate"],    "supportbot", 0.05),
    // Both apps
    rule("online.nc.hallucination", ["hallucination"],   "neoncart",   0.05),
    rule("online.sb.hallucination", ["hallucination"],   "supportbot", 0.05),
    rule("online.nc.json_valid",    ["jsonValid"],       "neoncart",   1.00),
    rule("online.sb.json_valid",    ["jsonValid"],       "supportbot", 1.00),
  ];

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
        console.log(`%c  ✓ ${r.rule_id.padEnd(30)} app=${r.match["tags.app"].padEnd(11)} → ${r.evaluator_ids.join(",")}`,
                    "color: #39ff7e;");
        results.ok.push(r.rule_id);
      } else if (resp.status === 409) {
        results.skipped.push(r.rule_id);
      } else {
        console.log(`%c  ✗ ${r.rule_id.padEnd(30)} HTTP ${resp.status}`,
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
