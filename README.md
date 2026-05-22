# ai-o11y-demo-apps

A self-contained AI observability demo: two AI-powered applications (NeonCart e-commerce + SupportBot internal employee chatbot) running on Kubernetes with full OpenTelemetry instrumentation sent to Grafana Cloud.

**Status:** 🚧 Active development — scaffolding underway. Not yet deployable.

## Who this is for

- **Grafana SEs** running customer-facing AI observability demos — clone, deploy in 5 minutes, walk through the dashboards.
- **Grafana customers** evaluating the AI o11y plugin — deploy a realistic-feeling app stack, see what their own AI workloads would look like instrumented.

## What this demo shows

- **NeonCart** — a public e-commerce site with an AI gift-finder and AI chatbot (25% of synthetic users use the AI features; 75% just shop)
- **SupportBot ("Ask Acme")** — Acme Corp's **internal employee chatbot**. Employees ask about HR policy, IT issues, payroll, benefits; an `sb-router` specialist delegates to domain specialists (billing, tech-support, account-management). Not customer-facing — this is the internal helpdesk pattern.
- **Full AI telemetry** — every LLM call instrumented via the Sigil SDK; cost, latency, tokens, evaluator results, all flowing to your Grafana Cloud
- **Multi-provider routing** — LLM gateway routes between Anthropic, OpenAI, Gemini, and Ollama with per-provider throughput caps
- **Realistic synthetic traffic** — K6 loadgen drives normal-but-varied user behavior across both apps

## Quick deploy (planned)

```bash
git clone https://github.com/stephenwagner-grafana/ai-o11y-demo-apps
cd ai-o11y-demo-apps
cp .env.example .env
# Fill in: CLAUDE_API_KEY, SIGIL_*, OTEL_EXPORTER_OTLP_*
./install.sh
```

Result: 5 namespaces, ~10 pods, telemetry flowing into your Grafana Cloud within a few minutes.

## Install requirements

1. A Kubernetes cluster (k3s / EKS / GKE / kind — anywhere)
2. A Claude API key (Anthropic — required)
3. Grafana Cloud org with **Sigil plugin enabled** (Sigil is the AI o11y plugin — required)
4. OTLP credentials from the Grafana Cloud OpenTelemetry card
5. Some way to reach NeonCart from a browser (your problem — `kubectl port-forward` works fine)

Optional: OpenAI / Gemini API keys, Ollama URL.

## Architecture

5 Kubernetes namespaces:

| Namespace | Component |
|---|---|
| `neoncart` | NC web frontend + `nc-chatbot` + `nc-gift-finder` specialists |
| `support-bot` | SB web frontend + `sb-router` + domain specialists |
| `llm-gateway` | The gatekeeper: routes requests across providers, enforces caps, emits cost |
| `ai-o11y-postgres` | Shared Postgres (NC product/user/transaction data + SB pgvector knowledge base) |
| `k6-loadgen` | Central loadgen driving both apps |

Telemetry: every pod emits OTLP directly to Grafana Cloud. Optionally route through customer's Alloy by overriding the OTLP endpoint env var.

## Design docs

Read these before contributing:

- [docs/METRICS.md](docs/METRICS.md) — the contract between apps and dashboards. Every metric, log, span attribute, and label.
- [docs/LOADGEN.md](docs/LOADGEN.md) — synthetic user behaviors, journey weights, gateway-throttle response.
- [docs/SIGIL_INTEGRATION.md](docs/SIGIL_INTEGRATION.md) — how the Sigil SDK is used, env vars, provider wrappers, workflow steps.

## Status

Scaffolding in progress. See open issues and the project board for current work.

## License

MIT
