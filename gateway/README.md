# llm-gateway

The gatekeeper. All AI calls from NeonCart + SupportBot specialists go through here. The gateway:

- Routes requests across configured providers (Anthropic, OpenAI, Gemini, Ollama)
- Enforces per-provider throughput caps ($-budget for cloud, GPU utilization for Ollama)
- Calls providers via the Sigil SDK's provider wrappers (automatic generation ingest + OTel)
- Computes cost from an embedded `config/pricing.yaml` (mirror of Sigil's canonical pricing)
- Exposes `/open` so the loadgen knows when to throttle

See [docs/SIGIL_INTEGRATION.md](../docs/SIGIL_INTEGRATION.md) for the deep architecture story.

## Endpoints

| Method | Path | Notes |
|---|---|---|
| `POST` | `/v1/llm` | Send a message, get a response. Header `X-Caller-Type: synthetic` for loadgen, omit for interactive (real-human, ungated → Anthropic). |
| `GET` | `/open` | Per-provider open/closed state. Loadgen polls this every ~5s. |
| `GET` | `/health` | Liveness. |
| `GET` | `/readyz` | Readiness + provider snapshot. |
| `GET` | `/metrics` | Prometheus metrics (currently `llm_gateway_up` only; full `llm_gateway_*` set TBD). |

## Phase 1 status

- ✅ FastAPI shell + endpoints
- ✅ OTel TracerProvider + MeterProvider setup (before Sigil init)
- ✅ Sigil client lifecycle (init / shutdown)
- ✅ `pricing.yaml` with Anthropic/OpenAI/Gemini/Ollama rates + env var override layer
- ✅ Cap tracking (rolling 24h $-spend for cloud; GPU utilization gauge for Ollama)
- ✅ Two-tier routing (synthetic vs interactive)
- ✅ Random-across-configured routing for synthetic
- ✅ `/open` endpoint shape locked
- 🚧 **Anthropic provider is a STUB** — the file documents the Sigil SDK wrapper integration but returns placeholder text. Real call lands once we verify the Sigil SDK API in a dev environment.
- 🚧 OpenAI / Gemini / Ollama providers are stubs
- ❌ `llm_gateway_*` Prom metrics not yet emitted (gateway works but dashboards won't have them)
- ❌ `gen_ai.client.cost.usd` emission (calculated, not yet emitted as OTel metric)

## Configuration (env vars)

**Provider auth:**
- `ANTHROPIC_API_KEY` (required for the demo)
- `OPENAI_API_KEY` (optional)
- `GEMINI_API_KEY` (optional)
- `OLLAMA_BASE_URL` (optional, e.g. `http://ollama:11434`)

**Caps:**
- `ANTHROPIC_CAP_USD_PER_DAY` (e.g. `20`)
- `OPENAI_CAP_USD_PER_DAY`
- `GEMINI_CAP_USD_PER_DAY`
- `OLLAMA_GPU_UTILIZATION_THRESHOLD` (0-1, default `0.85`)

**Default models:**
- `ANTHROPIC_DEFAULT_MODEL` (default `claude-haiku-4-5-20251001`)
- `OPENAI_DEFAULT_MODEL` (default `gpt-4o-mini`)
- `GEMINI_DEFAULT_MODEL` (default `gemini-1.5-flash`)
- `OLLAMA_DEFAULT_MODEL` (default `qwen2.5:32b`)

**Sigil (all required):**
- `SIGIL_ENDPOINT`, `SIGIL_PROTOCOL`, `SIGIL_AUTH_MODE`, `SIGIL_AUTH_TENANT_ID`, `SIGIL_AUTH_TOKEN`

**OTel (all required):**
- `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_HEADERS`

**Pricing overrides (optional, for negotiated discounts):**
- `ANTHROPIC_SONNET_OUTPUT_USD_PER_MTOKEN=15.00` (and similar for any model)

## Local dev

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
export ANTHROPIC_CAP_USD_PER_DAY=5
uvicorn app.main:app --reload --port 8000

curl http://localhost:8000/open
curl -X POST http://localhost:8000/v1/llm \
  -H 'content-type: application/json' \
  -d '{"messages":[{"role":"user","content":"hi"}], "user_id":"test", "app":"neoncart"}'
```

## Docker

```bash
docker build -t llm-gateway .
docker run --rm -p 8000:8000 --env-file .env llm-gateway
```
