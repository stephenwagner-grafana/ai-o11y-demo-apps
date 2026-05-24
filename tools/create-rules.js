// Paste into your Grafana DevTools Console while logged in.
// Creates the 13 Rules that wire the 18 evaluators (from create-evaluators.js)
// to their target traffic slices.
//
// Heuristic evaluator (sbPii) gets its rule via the parent — the 5 PII regex
// sub-evaluators are chained in automatically.
//
// Endpoint: POST {origin}/api/plugins/grafana-sigil-app/resources/eval/rules
//
// Run AFTER create-evaluators.js — rules reference evaluator IDs.
//
// One-liner (always fresh):
//   fetch('https://raw.githubusercontent.com/stephenwagner-grafana/ai-o11y-demo-apps/main/tools/create-rules.js?cb='+Date.now()).then(r=>r.text()).then(eval)

(async () => {
  const URL = `${window.location.origin}/api/plugins/grafana-sigil-app/resources/eval/rules`;
  const VERSION = new Date().toISOString().slice(0, 10);

  // ── Helper ──────────────────────────────────────────────────────────────────
  const rule = (id, evaluators, agentRegex, sampleRate) => ({
    rule_id: id,
    version: VERSION,
    enabled: true,
    selector: "user_visible_turn",
    match_criteria: [
      { key: "gen_ai.agent.name", op: "regex_match", value: agentRegex }
    ],
    sample_rate: sampleRate,
    evaluators,
  });

  // ── The 13 rules (one per evaluator, except sbPii covers piiSsn/..) ─────────
  const RULES = [
    rule("online.nc.quality.user_visible",     ["ncQuality"],       "nc-.*",                                          10),
    rule("online.sb.quality.user_visible",     ["sbQuality"],       "sb-.*",                                          10),
    rule("online.nc.groundedness",             ["ncGroundedness"],  "nc-chatbot|nc-gift-finder",                      15),
    rule("online.sb.groundedness",             ["sbGroundedness"],  "sb-billing|sb-tech-support|sb-account-management", 15),
    rule("online.hallucination",               ["hallucination"],   "nc-.*|sb-.*",                                     5),
    rule("online.sb.pii",                      ["sbPii"],           "sb-account-management|sb-billing",              100),
    rule("online.nc.sentiment",                ["ncSentiment"],     "nc-chatbot|nc-gift-finder",                      25),
    rule("online.json.valid",                  ["jsonValid"],       "nc-.*|sb-.*",                                   100),
    rule("online.sb.ai_usage",                 ["sbAiUsage"],       "sb-.*",                                          15),
    rule("online.nc.conciseness",              ["ncConciseness"],   "nc-.*",                                          10),
    rule("online.sb.conciseness",              ["sbConciseness"],   "sb-.*",                                          10),
    rule("online.sb.brand_voice",              ["sbBrandVoice"],    "sb-.*",                                          10),
    rule("online.sb.pirate_mate",              ["sbPirateMate"],    "sb-.*",                                           5),
  ];

  console.log(`%cCreating ${RULES.length} rules on ${window.location.origin}`,
              "font-weight: bold; color: #00f0ff;");

  const results = { ok: [], fail: [] };
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
        console.log(`%c  ✓ ${r.rule_id.padEnd(38)} → ${r.evaluators.join(",")}  HTTP ${resp.status}`,
                    "color: #39ff7e;");
        results.ok.push(r.rule_id);
      } else {
        console.log(`%c  ✗ ${r.rule_id.padEnd(38)} HTTP ${resp.status}`,
                    "color: #ff3b6b;");
        console.log(`      ${text.slice(0, 300)}`);
        results.fail.push({ id: r.rule_id, status: resp.status, body: text });
      }
    } catch (e) {
      console.log(`%c  ✗ ${r.rule_id} threw: ${e.message}`, "color: #ff3b6b;");
      results.fail.push({ id: r.rule_id, error: e.message });
    }
  }

  console.log(`\n%c${results.ok.length} created, ${results.fail.length} failed`,
              "font-weight: bold; color: #b537ff;");
  if (results.fail.length) console.table(results.fail);
  return results;
})();
