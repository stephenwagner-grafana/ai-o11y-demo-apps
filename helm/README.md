# Helm chart — ai-o11y-demo-apps

The chart that deploys every component of the demo into 5 namespaces on any Kubernetes cluster.

## Usage

Typical install via the wrapper:

```bash
./tools/install.sh
```

Direct Helm usage (if you've already generated your overrides file):

```bash
helm install ai-o11y-demo-apps ./helm \
  --create-namespace \
  --values overrides.yaml
```

## Structure

```
helm/
├── Chart.yaml
├── values.yaml                       — every knob the chart exposes
├── README.md                         — this file
└── templates/
    ├── _helpers.tpl                  — shared template helpers (image, labels, env blocks)
    ├── namespaces.yaml               — the 5 k8s namespaces
    ├── secrets.yaml                  — Sigil/OTel/provider/Postgres secrets per namespace
    ├── NOTES.txt                     — post-install message
    ├── postgres/                     — Postgres StatefulSet + Service + seed Job
    ├── gateway/                      — LLM gateway Deployment + Service + pricing ConfigMap
    ├── neoncart/                     — NC web + chatbot + gift-finder Deployments + Services
    ├── supportbot/                   — SB web + router + 3 domain specialists
    └── loadgen/                      — central loadgen Deployment + users ConfigMap + Service
```

## Required values (populated by `tools/install.sh`)

| Key | Source | Required? |
|---|---|---|
| `global.anthropic.apiKey` | `CLAUDE_API_KEY` | ✓ |
| `global.sigil.endpoint` / `tenantId` / `token` | Grafana Cloud → AI Observability → Configuration | ✓ |
| `global.otel.endpoint` / `headers` | Grafana Cloud → OpenTelemetry card | ✓ |
| `global.openai.apiKey` / `gemini.apiKey` / `ollama.baseUrl` | provider | optional |

See `helm/values.yaml` for everything else — all the knobs (cap thresholds, default models, replica counts, loadgen behavior knobs) live there.
