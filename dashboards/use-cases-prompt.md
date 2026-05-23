# Grafana Assistant prompt — ai-o11y-demo-apps Use Cases dashboard

Paste the entire block below into Grafana Assistant inside your Grafana
Cloud stack. Assistant will create one comprehensive use-case dashboard.

Every metric name + label in this prompt has been verified against live
data from the ai-o11y-demo-apps stack. The Assistant should not need
to invent anything.

---

```
Create a new dashboard called "ai-o11y-demo-apps — Use Cases" in the
default Grafana Cloud Prometheus + Loki + Tempo data sources for the
namespace service.namespace="ai-o11y-demo-apps".

GLOBAL DASHBOARD SETTINGS:
- time range: now-1h to now
- refresh: 30s
- tags: ai-o11y-demo-apps, demo, ai, use-cases
- variables (all multi-value, includeAll, allValue=".+"):
    agent     = label_values(gen_ai_client_operation_duration_seconds_count{service_namespace="ai-o11y-demo-apps"}, gen_ai_agent_name)
    provider  = label_values(gen_ai_client_operation_duration_seconds_count{service_namespace="ai-o11y-demo-apps"}, gen_ai_provider_name)
    model     = label_values(gen_ai_client_operation_duration_seconds_count{service_namespace="ai-o11y-demo-apps"}, gen_ai_request_model)
- EVERY query that filters on these MUST use ${var:regex} syntax, not bare $var.
- OTel meter export interval is 60s — use rate windows >= [5m].

METRICS AVAILABLE (all verified live in Prom):

GenAI / sigil-sdk (no user_id on these — SDK limitation):
- gen_ai_client_operation_duration_seconds_{count,sum,bucket}
    attrs: gen_ai_agent_name, gen_ai_provider_name, gen_ai_request_model,
           error_type, error_category
- gen_ai_client_token_usage_{sum,count,bucket}     + attr gen_ai_token_type
- gen_ai_client_tool_calls_per_operation_count_{sum,count,bucket}
    (no gen_ai_tool_name attr; slice by gen_ai_agent_name)
- gen_ai_client_time_to_first_token_seconds_*  (empty — non-streaming)

Gateway-owned custom (these DO have user_id):
- gen_ai_client_cost_usd_total
    attrs: gen_ai_system, gen_ai_request_model, gen_ai_agent_name, user_id
- gen_ai_user_calls_total
    attrs: gen_ai_system, gen_ai_request_model, gen_ai_agent_name, user_id
- gen_ai_user_tokens_total
    attrs: gen_ai_system, gen_ai_request_model, gen_ai_agent_name, user_id, gen_ai_token_type

NeonCart application:
- neoncart_session_starts_total                 attr user_domain
- neoncart_session_used_ai_total                attr user_domain
- neoncart_page_views_total                     attrs user_domain, page
- neoncart_search_queries_total                 attr user_domain
- neoncart_product_views_total                  attrs user_domain, product_sku
- neoncart_add_to_cart_total                    attrs source, user_domain, product_sku
- neoncart_transactions_total                   attr user_domain
- neoncart_revenue_usd_total                    attr user_domain
- neoncart_ai_attributed_revenue_usd_total      attrs source, gen_ai_agent_name
    (cart-value attributed to the AI agent that drove the ATC; used for ROI ratio)

Loadgen:
- loadgen_k6_restarts_total                     attr scenario

HTTP server (OTel autoinstrument):
- http_server_duration_milliseconds_{count,sum,bucket}    attr service_name

LAYOUT — 10 rows, ~30 panels:

ROW 1 — 🎯 KPI Headlines (6 stat panels, full width, 4 wide each):
- Total Requests (1h): sum(increase(gen_ai_client_operation_duration_seconds_count{service_namespace="ai-o11y-demo-apps",gen_ai_agent_name=~"${agent:regex}",gen_ai_provider_name=~"${provider:regex}",gen_ai_request_model=~"${model:regex}"}[1h]))
- Total Tokens (1h): sum(increase(gen_ai_client_token_usage_sum{service_namespace="ai-o11y-demo-apps",gen_ai_agent_name=~"${agent:regex}",gen_ai_provider_name=~"${provider:regex}",gen_ai_request_model=~"${model:regex}"}[1h]))
- Total Spend (1h) — unit currencyUSD: sum(increase(gen_ai_client_cost_usd_total{service_namespace="ai-o11y-demo-apps",gen_ai_agent_name=~"${agent:regex}",gen_ai_request_model=~"${model:regex}"}[1h]))
- p95 Latency — unit s, thresholds green<3, yellow<8, red: histogram_quantile(0.95, sum by (le) (rate(gen_ai_client_operation_duration_seconds_bucket{service_namespace="ai-o11y-demo-apps",gen_ai_agent_name=~"${agent:regex}"}[5m])))
- Error Rate % — unit percent, thresholds green<5, yellow<25, red: sum(rate(gen_ai_client_operation_duration_seconds_count{service_namespace="ai-o11y-demo-apps",error_type!="",gen_ai_agent_name=~"${agent:regex}"}[5m])) / sum(rate(gen_ai_client_operation_duration_seconds_count{service_namespace="ai-o11y-demo-apps",gen_ai_agent_name=~"${agent:regex}"}[5m])) * 100
- Active Agents: count(count by (gen_ai_agent_name) (rate(gen_ai_client_operation_duration_seconds_count{service_namespace="ai-o11y-demo-apps"}[5m]) > 0))

ROW 2 — 🤖 Provider & Model Diversity (3 timeseries, 8 wide each):
- Requests/sec by Provider: sum by (gen_ai_provider_name) (rate(gen_ai_client_operation_duration_seconds_count{service_namespace="ai-o11y-demo-apps",gen_ai_agent_name=~"${agent:regex}",gen_ai_provider_name=~"${provider:regex}",gen_ai_request_model=~"${model:regex}"}[5m]))
- Requests/sec by Model: sum by (gen_ai_request_model) (...same filter...)
- Requests/sec by Agent: sum by (gen_ai_agent_name) (...same filter...)

ROW 3 — 📊 Performance — latency & tokens (4 timeseries, 12 wide each, 2x2 grid):
- p95 Latency by Agent: histogram_quantile(0.95, sum by (le, gen_ai_agent_name) (rate(gen_ai_client_operation_duration_seconds_bucket{service_namespace="ai-o11y-demo-apps",gen_ai_agent_name=~"${agent:regex}",gen_ai_provider_name=~"${provider:regex}",gen_ai_request_model=~"${model:regex}"}[5m])))
- p95 Latency by Model: histogram_quantile(0.95, sum by (le, gen_ai_request_model) (...same filter...))
- Tokens/sec by Type: sum by (gen_ai_token_type) (rate(gen_ai_client_token_usage_sum{service_namespace="ai-o11y-demo-apps",gen_ai_agent_name=~"${agent:regex}",gen_ai_provider_name=~"${provider:regex}",gen_ai_request_model=~"${model:regex}"}[5m]))
- Tokens/sec by Model: sum by (gen_ai_request_model) (...same filter on token_usage_sum...)

ROW 4 — 💰 Cost economics (3 timeseries currencyUSD, 8 wide each):
- Spend $/hr by Agent: sum by (gen_ai_agent_name) (rate(gen_ai_client_cost_usd_total{service_namespace="ai-o11y-demo-apps",gen_ai_agent_name=~"${agent:regex}",gen_ai_request_model=~"${model:regex}"}[5m])) * 3600
- Spend $/hr by Model: sum by (gen_ai_request_model) (rate(gen_ai_client_cost_usd_total{service_namespace="ai-o11y-demo-apps",gen_ai_request_model=~"${model:regex}",gen_ai_agent_name=~"${agent:regex}"}[5m])) * 3600
- Spend $/hr by Provider: sum by (gen_ai_system) (rate(gen_ai_client_cost_usd_total{service_namespace="ai-o11y-demo-apps",gen_ai_agent_name=~"${agent:regex}",gen_ai_request_model=~"${model:regex}"}[5m])) * 3600

ROW 5 — 🔧 Tool Calls (1 timeseries full width):
- Tool Calls/min by Agent: sum by (gen_ai_agent_name) (rate(gen_ai_client_tool_calls_per_operation_count_sum{service_namespace="ai-o11y-demo-apps",gen_ai_agent_name=~"${agent:regex}"}[5m])) * 60

ROW 6 — 🎯 AI Agent ROI (3 panels, this is the headline metric):
- ROI ratio over time — unit none, thresholds red<1, yellow<10, green:
    sum by (gen_ai_agent_name) (rate(neoncart_ai_attributed_revenue_usd_total[15m])) / on(gen_ai_agent_name) sum by (gen_ai_agent_name) (rate(gen_ai_client_cost_usd_total{service_namespace="ai-o11y-demo-apps",gen_ai_agent_name=~"nc-.*"}[15m]))
    legendFormat: {{gen_ai_agent_name}}
- Cumulative ROI multiple — stat panel with thresholds red<1, yellow<10, green; one tile per gen_ai_agent_name:
    sum by (gen_ai_agent_name) (neoncart_ai_attributed_revenue_usd_total) / on(gen_ai_agent_name) sum by (gen_ai_agent_name) (gen_ai_client_cost_usd_total{service_namespace="ai-o11y-demo-apps",gen_ai_agent_name=~"nc-.*"})
- Cart value $/hr vs Token cost $/hr — 2-query timeseries, currencyUSD:
    A: sum by (gen_ai_agent_name) (rate(neoncart_ai_attributed_revenue_usd_total[5m])) * 3600   legend "{{gen_ai_agent_name}} — cart value"   color green
    B: sum by (gen_ai_agent_name) (rate(gen_ai_client_cost_usd_total{service_namespace="ai-o11y-demo-apps",gen_ai_agent_name=~"nc-.*"}[5m])) * 3600   legend "{{gen_ai_agent_name}} — token cost"   color red

ROW 7 — 🛒 NeonCart Business Funnel (3 timeseries + 4 stat panels):
- Sessions/min by Domain: sum by (user_domain) (rate(neoncart_session_starts_total{service_namespace="ai-o11y-demo-apps"}[5m])) * 60
- Add-to-Cart by Source: sum by (source) (rate(neoncart_add_to_cart_total{service_namespace="ai-o11y-demo-apps"}[5m]))
- Revenue $/hr (no group): sum(rate(neoncart_revenue_usd_total{service_namespace="ai-o11y-demo-apps"}[5m])) * 3600
- 4 stat panels (Page Views / Search Queries / Product Views / Transactions, all 1h):
    sum(increase(neoncart_{page_views|search_queries|product_views|transactions}_total{service_namespace="ai-o11y-demo-apps"}[1h]))

ROW 8 — 🩺 Service Health (HTTP) (2 timeseries):
- HTTP request rate by service: sum by (service_name) (rate(http_server_duration_milliseconds_count{service_namespace="ai-o11y-demo-apps"}[5m]))
- HTTP p95 by service — unit ms: histogram_quantile(0.95, sum by (le, service_name) (rate(http_server_duration_milliseconds_bucket{service_namespace="ai-o11y-demo-apps"}[5m])))

ROW 9 — 🔗 Sigil deep-dive (text/markdown panel, full width):
Content mentions /a/grafana-sigil-app/conversations and /a/grafana-sigil-app/analytics
links. List the demo's use cases: multi-model routing, multi-provider, tool use,
multi-turn history, AI ROI metric, "show me mice" trap (nc-chatbot's search_products
tool queries a non-existent `species` column), NeonCart conversion funnel, cost transparency.

ROW 10 — 👥 SupportBot — per-employee usage:

Panel A (table, full width 24h × 9 high, sorted by Calls desc):
Four range queries (instant=true, format=table) over [1h]:
  calls:      sum by (user_id) (increase(gen_ai_user_calls_total{service_namespace="ai-o11y-demo-apps",gen_ai_agent_name=~"sb-.*"}[1h]))
  input_tok:  sum by (user_id) (increase(gen_ai_user_tokens_total{service_namespace="ai-o11y-demo-apps",gen_ai_agent_name=~"sb-.*",gen_ai_token_type="input"}[1h]))
  output_tok: sum by (user_id) (increase(gen_ai_user_tokens_total{service_namespace="ai-o11y-demo-apps",gen_ai_agent_name=~"sb-.*",gen_ai_token_type="output"}[1h]))
  cost:       sum by (user_id) (increase(gen_ai_client_cost_usd_total{service_namespace="ai-o11y-demo-apps",gen_ai_agent_name=~"sb-.*"}[1h]))
Transformations:
  joinByField user_id outer
  organize: rename user_id→Employee, Value #calls→Calls, Value #input_tok→Input Tokens, Value #output_tok→Output Tokens, Value #cost→Cost (USD)
  sortBy Calls desc
Overrides: Cost (USD) unit=currencyUSD decimals=4 cellOptions=color-background mode=continuous-GrYlRd; Calls cellOptions=color-background mode=continuous-BlPu.

Panel B (timeseries, 12 wide × 9 high) — Top 10 SB employees — calls/min:
  topk(10, sum by (user_id) (rate(gen_ai_user_calls_total{service_namespace="ai-o11y-demo-apps",gen_ai_agent_name=~"sb-.*"}[5m]) * 60))
  legendFormat: {{user_id}}

Panel C (timeseries stacked area, 12 wide × 9 high) — Tokens/sec by SB employee:
  topk(10, sum by (user_id) (rate(gen_ai_user_tokens_total{service_namespace="ai-o11y-demo-apps",gen_ai_agent_name=~"sb-.*"}[5m])))
  custom.stacking.mode = normal

Panels D / E / F / G (4 stat panels, 6 wide × 5 high each, color-background):
- Active SB employees (last 1h):
    count(count by (user_id) (increase(gen_ai_user_calls_total{service_namespace="ai-o11y-demo-apps",gen_ai_agent_name=~"sb-.*"}[1h]) > 0))
- Avg calls per employee (1h):
    avg(sum by (user_id) (increase(gen_ai_user_calls_total{service_namespace="ai-o11y-demo-apps",gen_ai_agent_name=~"sb-.*"}[1h])))
- Avg tokens per employee (1h):
    avg(sum by (user_id) (increase(gen_ai_user_tokens_total{service_namespace="ai-o11y-demo-apps",gen_ai_agent_name=~"sb-.*"}[1h])))
- Avg cost per employee (1h) — unit currencyUSD:
    avg(sum by (user_id) (increase(gen_ai_client_cost_usd_total{service_namespace="ai-o11y-demo-apps",gen_ai_agent_name=~"sb-.*"}[1h])))

Save with title "ai-o11y-demo-apps — Use Cases" and commit message
"Create comprehensive use-case dashboard for ai-o11y-demo-apps."
```
