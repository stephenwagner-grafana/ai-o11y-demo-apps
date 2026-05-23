# Dashboards

Three ways to get the ai-o11y-demo-apps dashboards in your Grafana:

## Importing the Use Cases dashboard (UI — zero setup)

After install:

1. Go to Grafana → Dashboards → **New** → **Import**
2. Upload `dashboards/use-cases.json` (or paste the file contents)
3. Select your Prometheus datasource when prompted (the one receiving
   `gen_ai_*` / `neoncart_*` metrics from this stack — usually the default
   `grafanacloud-prom` on Grafana Cloud)
4. Click **Import**. The dashboard populates immediately from live data.

## Option A — Paste the Assistant prompt (no API token needed)

Open Grafana Assistant in your Grafana Cloud instance and paste
`use-cases-prompt.md` (the whole file). The Assistant will create a
new dashboard called **"ai-o11y-demo-apps — Use Cases"** that covers
every demo use case: KPI headlines, multi-provider/multi-model routing,
per-agent slices, cost economics, tool calls, **AI Agent ROI**, NeonCart
funnel, service health, and **per-employee SupportBot usage**.

Every query in the prompt has been verified against live metrics from
this stack — no speculative panels.

## Option B — Import the JSON via API (scriptable, needs API token)

If you have a Grafana service-account API token, run:

```bash
export GRAFANA_URL=https://YOUR-STACK.grafana.net
export GRAFANA_API_TOKEN=glsa_XXX
# Optional: override if your Prometheus datasource UID is not the
# default "grafanacloud-prom":
# export PROM_DS_UID=my-prom-uid

./dashboards/import.sh
```

This POSTs every `.json` file in this directory to your Grafana. Files
with a portable `__inputs` block (e.g. `use-cases.json`) go through
`/api/dashboards/import` with `${DS_PROMETHEUS}` resolved to
`$PROM_DS_UID`; everything else falls back to `/api/dashboards/db`.

## What's in the demo's dashboards

The use-case dashboard covers ten rows / ~30 panels:

| Row | What it shows |
|---|---|
| 🎯 KPI Headlines | Total Requests, Tokens, Spend, p95 Latency, Error Rate, Active Agents |
| 🤖 Provider & Model Diversity | Per-provider / per-model / per-agent throughput |
| 📊 Performance | p95 latency per agent + per model, tokens/sec by type + by model |
| 💰 Cost economics | Spend $/hr by agent / model / provider |
| 🔧 Tool Calls | Tool invocation rate per agent |
| 🎯 AI Agent ROI | The headline metric: cart-value generated per AI agent vs token cost. ROI ratio over time, cumulative ROI multiple, cart-value vs cost side-by-side. |
| 🛒 NeonCart Business Funnel | Sessions/min, ATC by source, revenue, plus 4 KPI stats |
| 🩺 Service Health (HTTP) | Per-service request rate + p95 |
| 🔗 Sigil deep-dive | Text panel with conversation-thread links |
| 👥 SupportBot — per-employee usage | Per-employee call count, input/output tokens, cumulative cost in a sortable table. Plus per-employee call rate + token rate timeseries + four "average per employee" stat panels. Acme employees only (filters via `gen_ai_agent_name=~"sb-.*"`). |

## Metrics behind it all

All custom metrics are emitted by the gateway / apps over OTLP, no
Prom scrape config needed. Discoverable via
`mcp__grafana__list_prometheus_metric_names` with regex `gen_ai_.*` or
`neoncart_.*`.

Most useful labels:

- `gen_ai_agent_name` — nc-chatbot / nc-gift-finder / sb-router / sb-billing / sb-tech-support / sb-account-management
- `gen_ai_provider_name` — anthropic / ollama
- `gen_ai_request_model` — claude-haiku-4-5-20251001 / claude-sonnet-4-6 / claude-opus-4-7 / qwen2.5:3b / qwen2.5:7b / qwen2.5:14b / llama3.1:8b
- `gen_ai_token_type` — input / output / cache_read / cache_write / reasoning
- `user_id` — present on `gen_ai_user_calls_total`, `gen_ai_user_tokens_total`, and `gen_ai_client_cost_usd_total` (NOT on the sigil-sdk-emitted operation_duration / token_usage metrics — SDK limitation)
- `source` (on `neoncart_add_to_cart_total` and `neoncart_ai_attributed_revenue_usd_total`) — manual / ai_chatbot / ai_gift_finder
- `user_domain` (on `neoncart_*`) — gmail.com / aol.com / yahoo.com / unknown
