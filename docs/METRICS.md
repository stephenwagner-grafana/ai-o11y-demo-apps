# Metric inventory — ai-o11y-demo-apps

**Status:** Draft v0.2 (2026-05-22). Living document — update as components ship.

This doc is the contract between apps and dashboards. Anything not listed shouldn't be emitted; anything listed should have at least one panel using it.

For the Sigil SDK setup itself (env vars, code patterns, provider wrappers, workflow steps), see [SIGIL_INTEGRATION.md](SIGIL_INTEGRATION.md).

## Conventions

- **App-level metrics:** `<app>_<thing>_<unit>_<type>` — e.g., `neoncart_revenue_usd_total`
- **AI conversation metrics:** OTel GenAI semantic conventions — `gen_ai.client.*` (emitted automatically by Sigil SDK)
- **Gateway internal:** `llm_gateway_*`
- **Sigil evals:** `sigil_eval_*` (defined by Sigil plugin, not by us)
- **Auto-emitted (infra):** OTel HTTP/DB semconv (`http.server.*`, `db.client.*`)

All metrics emit via OTLP **directly to Grafana Cloud** by default (customer with Alloy can override the endpoint).

## Resource attributes (on every metric, log, span)

- `service.name` — one of: `neoncart-web`, `neoncart-chatbot`, `neoncart-gift-finder`, `supportbot-web`, `supportbot-router`, `supportbot-<domain>`, `llm-gateway`, `loadgen`
- `service.namespace` — `ai-o11y-demo-apps` (logical grouping, distinct from k8s namespace)
- `service.version` — from build
- `k8s.namespace.name` — one of the 5 k8s namespaces (see ARCHITECTURE.md)

## Conversation labels (on AI-related metrics, spans, logs)

- `session_id` — unique per browser session. A session can contain multiple conversations.
- `gen_ai.conversation.id` — unique per conversation (OTel standard, used by Sigil). Must be unique per (session, user).
- `user_id` — synthetic email (`<name>@gmail.com` / `aol.com` / `yahoo.com` for NC; `<name>@acme.com` for SB)
- `app` — `neoncart` or `supportbot`
- `gen_ai.agent.name` — specialist name (`nc-chatbot`, `nc-gift-finder`, `sb-router`, `sb-billing`, etc.)
- `gen_ai.agent.version` — specialist code version (Sigil tracks regressions across versions)
- `gen_ai.tool.name` — present on metrics/spans for LLM calls that invoke a tool
- `caller_type` — `synthetic` (loadgen) or `interactive` (real human)

## NeonCart — app metrics

| Name | Type | Labels | Source pod | Notes |
|---|---|---|---|---|
| `neoncart_active_sessions` | Gauge | — | `nc-web` | Current active browser sessions |
| `neoncart_session_starts_total` | Counter | `user_domain` | `nc-web` | New sessions |
| `neoncart_page_views_total` | Counter | `page`, `user_domain` | `nc-web` | page ∈ {main, search, product, cart, checkout} |
| `neoncart_search_queries_total` | Counter | `user_domain` | `nc-web` | Text search executed |
| `neoncart_product_views_total` | Counter | `product_sku`, `user_domain` | `nc-web` | Single-product page hit |
| `neoncart_add_to_cart_total` | Counter | `product_sku`, `source`, `user_domain` | `nc-web` | source ∈ {ai_gift_finder, ai_chatbot, manual} |
| `neoncart_transactions_total` | Counter | `user_domain` | `nc-web` | Completed checkouts |
| `neoncart_revenue_usd_total` | Counter | `user_domain` | `nc-web` | Transaction $ summed |
| `neoncart_session_used_ai_total` | Counter | `user_domain` | `nc-web` | Sessions where AI was invoked ≥1 time |

**Derivable:**
- AI adoption %: `neoncart_session_used_ai_total / neoncart_session_starts_total`
- Revenue (any window): `increase(neoncart_revenue_usd_total[1h])` / `[1d]` / `[7d]` / `[30d]`. One dashboard, four panels covers hourly through monthly.
- AI-attributed revenue %: filter `neoncart_add_to_cart_total{source=~"ai_.*"}` and join to revenue events

**Caveat on `increase()`:** on a counter younger than the window, returns partial. "Last 30 days" on a 5-day-old deploy shows 5 days. Correct behavior, just be ready to explain in demos.

## SupportBot — app metrics

| Name | Type | Labels | Source pod | Notes |
|---|---|---|---|---|
| `supportbot_active_sessions` | Gauge | — | `sb-web` | Currently chatting users |
| `supportbot_conversations_total` | Counter | `user_domain` | `sb-web` | Conversation starts |
| `supportbot_conversation_turns_total` | Counter | `domain_specialist`, `user_domain` | `sb-web` | Per-turn count |
| `supportbot_conversation_duration_seconds` | Histogram | `domain_specialist` | `sb-web` | Wall-clock convo time |
| `supportbot_router_decisions_total` | Counter | `domain_specialist` | `sb-router` | Router → domain specialist routing |
| `supportbot_router_unable_to_route_total` | Counter | — | `sb-router` | Off-topic / can't route |

## AI conversations — OTel GenAI metrics (emitted automatically by Sigil SDK)

The Sigil SDK emits these four OTel metrics on every LLM call. We don't write them ourselves — using the Sigil provider wrappers gets them for free.

| Name | Type | Key labels | Notes |
|---|---|---|---|
| `gen_ai.client.token.usage` | Histogram | `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.operation.name`, `gen_ai.token.type` (input/output), `session_id`, `gen_ai.conversation.id`, `user_id`, `app`, `gen_ai.agent.name`, `gen_ai.tool.name` (if tool call), `caller_type` | OTel standard |
| `gen_ai.client.operation.duration` | Histogram | same as above | OTel standard |
| `gen_ai.client.time_to_first_token` | Histogram | same as above | OTel standard — important for streaming UX panels |
| `gen_ai.client.tool_calls_per_operation` | Histogram | same as above + `gen_ai.tool.name` always present | OTel standard — how many tools a generation invoked |
| `gen_ai.client.cost.usd` | Counter | `gen_ai.provider.name`, `gen_ai.response.model`, `session_id`, `gen_ai.conversation.id`, `user_id`, `app`, `gen_ai.agent.name`, `caller_type` | **Project-specific** (Sigil doesn't emit Prom cost today — see Cost calculation below) |

## Sigil generation span attributes (required on every LLM span)

Sigil's generation ingest captures these via the SDK's `set_result`/`SetResult` call. The SDK populates most of them automatically when using provider wrappers. Listed here so dashboards/queries know what's available for filtering and grouping.

**Identity and routing:**
- `gen_ai.operation.name` — `chat` / `text_completion` / `embeddings` / etc.
- `sigil.generation.id` — Sigil-generated unique ID per LLM call
- `gen_ai.conversation.id`
- `gen_ai.agent.name`, `gen_ai.agent.version`
- `sigil.generation.parent_generation_ids` — multi-agent dependency tracking (see below)
- `sigil.sdk.name` — which Sigil SDK emitted this

**Model:**
- `gen_ai.provider.name` — `anthropic` / `openai` / `gemini` / `ollama`
- `gen_ai.request.model` — what the caller asked for (e.g., `claude-sonnet-4-6`)
- `gen_ai.response.model` — what the provider actually used (often the same; can differ on auto-routing)

**Request controls:**
- `gen_ai.request.max_tokens`
- `gen_ai.request.temperature`
- `gen_ai.request.top_p`
- `sigil.gen_ai.request.tool_choice`
- `sigil.gen_ai.request.thinking.enabled`
- `sigil.gen_ai.request.thinking.budget_tokens`

**Usage and outcomes:**
- `gen_ai.usage.input_tokens`
- `gen_ai.usage.output_tokens`
- `gen_ai.usage.cache_read_input_tokens` — Anthropic prompt caching (cheaper input)
- `gen_ai.usage.cache_creation_input_tokens` — Anthropic prompt caching (one-time cost)
- `gen_ai.usage.reasoning_tokens` — for thinking-enabled models
- `gen_ai.response.finish_reasons`
- `error.type`, `error.category` — when the call failed

## Sigil workflow steps (agentic pipelines)

Sigil has a separate ingest pipeline for **workflow steps** — non-LLM nodes in an agentic graph. We use it for SB's router → domain specialist routing (which is a non-LLM decision step before an LLM call).

Each workflow step captures:
- `id` — unique step ID (`wfs_<hex>`)
- `conversation_id` — links step to a conversation
- `step_name` — node name (e.g., `route_question`, `select_specialist`)
- `framework` — `langgraph` / `custom` / etc.
- `started_at` / `completed_at`
- `input_state` — node input (the user's raw question)
- `output_state` — node output (the selected specialist)
- `error` — if the node failed
- `linked_generation_ids` — generation IDs of LLM calls inside this step (the router LLM call that made the decision)
- `parent_step_ids` — DAG edges between nodes
- `agent_name`, `agent_version`
- `trace_id`, `span_id` — OTel correlation

The Sigil UI builds the execution graph from these. Without workflow steps, SB looks like "a chatbot makes an LLM call" — with workflow steps, you see "router decides → domain specialist runs."

## Multi-agent dependency tracking

When one specialist's output feeds into another, set `parent_generation_ids` on the downstream generation. Sigil uses this to build a DAG and propagate eval signals.

Example: `nc-gift-finder` produces 3 recommendations → `nc-chatbot` summarizes them in response to a follow-up question:
- Gift-finder generation: `parent_generation_ids = []`
- Chatbot generation: `parent_generation_ids = [<gift_finder_generation_id>]`

If a gift-finder eval fails ("recommendations were off-topic"), Sigil flags the dependent chatbot generation too.

## Cost calculation (where USD numbers come from)

**Sigil does NOT emit a Prom cost metric today** (confirmed via Sigil docs 2026-05-22). Sigil computes cost server-side from generation token data and surfaces it in its own Analytics UI (`/a/grafana-sigil-app/analytics`). No `sigil_cost_usd_total` exists; no public pricing API exists.

**Implication:** if we want cost as a queryable Prom metric for our custom dashboards (cost-vs-revenue, cost-per-user, etc.), the gateway has to compute it.

**Approach (locked 2026-05-22):**
- Gateway maintains a small `pricing.yaml` mirroring Anthropic/OpenAI/Gemini published pricing
- Gateway calculates `cost_usd = (input_tokens × input_rate + output_tokens × output_rate) / 1_000_000`
- Gateway emits `gen_ai.client.cost.usd` as a Counter (see metrics table above)
- File `pricing.yaml` explicitly comments "mirror of Sigil's pricing; remove when Sigil ships a Prom metric or public pricing API"
- Customer can override individual rates via env vars (e.g., `ANTHROPIC_SONNET_OUTPUT_USD_PER_MTOKEN=15.00`)
- Filed/open feature request with Sigil eng to add native cost emission

**Ollama (local):** Static `$/1M-output-tokens` rate.
- Env var: `OLLAMA_OUTPUT_USD_PER_MTOKEN` (default `0.30` — midpoint of wags-ai cost model range)
- Calculation: `cost_per_call = output_tokens × OLLAMA_OUTPUT_USD_PER_MTOKEN / 1_000_000`
- Input tokens NOT counted (cheap on local inference)
- Same `gen_ai.client.cost.usd` metric, same labels

**Deferred (extension):** Real-time GPU-power formula. Requires GPU-power sensor metric.

## LLM Gateway — internal metrics

| Name | Type | Labels | Notes |
|---|---|---|---|
| `llm_gateway_requests_total` | Counter | `provider`, `model`, `status` (ok/throttled/error), `preferred_provider`, `caller_type` | Per-request outcome |
| `llm_gateway_provider_open` | Gauge | `provider` | 1 = open, 0 = closed |
| `llm_gateway_provider_spent_usd_today` | Gauge | `provider`, `caller_type` | Rolling 24h (or calendar day — TBD). Split by caller_type lets dashboards show human vs loadgen spend. |
| `llm_gateway_provider_cap_usd` | Gauge | `provider` | Configured cap |
| `llm_gateway_provider_gpu_utilization_ratio` | Gauge | `provider` | Ollama only; 0-1 |
| `llm_gateway_provider_state_change_total` | Counter | `provider`, `direction` (open_to_closed / closed_to_open) | State transition events |

## Sigil evals (queryable in Prometheus)

| Name | Type | Labels | Notes |
|---|---|---|---|
| `sigil_eval_executions_total` | Counter | `evaluator`, `status`, `gen_ai_agent_name` | Eval run count (note: `_executions_total`, not `_result_total`; `status` not `verdict`) |

Sigil eval scores per-conversation typically flow as log lines, not metrics, but check Sigil docs for current state.

## Infra (auto-emitted via OTel auto-instrument)

- `http.server.request.duration` — per service, per endpoint, per status — from FastAPI/Next.js auto-instrument
- `http.server.active_requests` — per service
- `db.client.operation.duration` — Postgres queries (via psycopg/pg-promise instrumentation)
- Pod CPU/memory/restarts — from customer's k8s integration (separate from this app's OTLP)

## Logs (structured JSON to stdout → Loki via customer's pipeline)

Every log line includes:
- `timestamp` (ISO8601 UTC)
- `level` (debug/info/warn/error)
- `service.name`
- `request_id` (per HTTP request)
- `session_id` (when applicable)
- `user_id` (when applicable)
- `gen_ai.conversation.id` (when applicable)
- `message`

**LLM call logs (from gateway)** include the full request/response/tokens/cost/latency/provider/model. Sigil consumes the generation ingest separately.

## Traces

- OTel auto-instrument on each web framework (FastAPI / Next.js)
- LLM call spans created by Sigil SDK (we don't write them manually)
- DB query auto-spans (via DB driver instrumentation)
- **Required span attributes on every AI-related span** (Sigil-required for AI o11y plugin):
  - `session.id` (note: OTel uses `session.id`, mirrored from `session_id` in our labels)
  - `user.id`
  - `service.namespace`
  - `gen_ai.agent.name`
  - `gen_ai.conversation.id`
- See [SIGIL_INTEGRATION.md](SIGIL_INTEGRATION.md) for the SDK setup that ensures these are populated.

## Things explicitly NOT instrumented (base scope)

- Scripted bad-actor behavior — lives in extensions
- Tempo Metrics Generator — not enabled; we emit explicit metrics
- Prometheus recording rules — none upfront; promote on demand if a query is slow
- Custom OTel collector pod — apps emit OTLP directly
- Raw provider artifacts (full request/response bodies) — Sigil supports this but it's default OFF for privacy; only enable via debug opt-in
