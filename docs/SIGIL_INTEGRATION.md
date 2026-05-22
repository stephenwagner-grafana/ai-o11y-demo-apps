# Sigil integration — ai-o11y-demo-apps

**Status:** Draft v0.1 (2026-05-22).

How the apps integrate with Sigil. Sigil is a hard install requirement (it owns evals + canonical pricing data + the AI o11y plugin UI).

**Authoritative references:**
- SDK source: https://github.com/grafana/sigil-sdk
- Product docs: https://grafana.com/docs/grafana-cloud/machine-learning/ai-observability/

## Required environment variables

Every pod that talks to an LLM (i.e. the gateway, possibly specialists if they call directly) needs these set BEFORE the Sigil SDK is created:

```
SIGIL_ENDPOINT=https://sigil-prod-us-east-0.grafana.net
SIGIL_PROTOCOL=http
SIGIL_AUTH_MODE=basic
SIGIL_AUTH_TENANT_ID=<numeric tenant id>
SIGIL_AUTH_TOKEN=<glc_... token, scoped sigil:write metrics:write traces:write logs:write>

OTEL_EXPORTER_OTLP_ENDPOINT=<from stack OpenTelemetry card>
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic <base64 of "<otlp-instance-id>:<glc_... token>">
```

**Where customer finds these values:**
- `SIGIL_ENDPOINT`, `SIGIL_AUTH_TENANT_ID`: Grafana Cloud → AI Observability → Configuration
- `SIGIL_AUTH_TOKEN`: Stack Administration → Users and access → Cloud Access Policies. Scope with `sigil:write` + `metrics:write` + `traces:write` + `logs:write`. Token starts with `glc_`.
- `OTEL_EXPORTER_OTLP_ENDPOINT` + OTLP basic-auth username: Cloud portal → stack details → OpenTelemetry card. The OTLP instance ID may differ from `SIGIL_AUTH_TENANT_ID` — copy verbatim.

**Computing the `OTEL_EXPORTER_OTLP_HEADERS` value:**
```
printf '%s' '<otlp-instance-id>:<glc_token>' | base64 | tr -d '\n'
```
`tr -d '\n'` is mandatory — trailing newline silently breaks the header.

## Gateway uses Sigil's provider wrappers (don't call raw provider SDKs)

The Sigil SDK ships provider wrappers that already do the right instrumentation. The gateway should use these instead of calling `anthropic`, `openai`, or `google-generativeai` directly.

**Why:** Provider wrappers automatically populate generation ingest fields (request/response models, tokens including cache reads/reasoning, finish reasons, tool calls, errors). Rolling our own instrumentation duplicates ~hundreds of lines of careful field-capture code and is the most common source of bugs in AI o11y demos.

**Python (the gateway's language):**
- `python-providers/anthropic`
- `python-providers/openai`
- `python-providers/gemini`
- Ollama: no Sigil wrapper exists. We call Ollama's HTTP API directly + manually emit generation ingest using `client.start_generation(...)` + `client.enqueue_workflow_step(...)` if needed.

Other language SDKs (Go, JS/TS, Java, .NET) exist if we ever rewrite the gateway.

## OTel TracerProvider + MeterProvider setup (REQUIRED before SDK creation)

The Sigil SDK emits OTel spans and metrics but **does NOT create OTel providers itself**. Without configured providers, telemetry goes to the default no-op and is silently lost.

Initialize providers FIRST, then create the Sigil client:

```python
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

resource = Resource.create({
    "service.name": "llm-gateway",
    "service.namespace": "ai-o11y-demo-apps",
    "service.version": "<version>",
})

tp = TracerProvider(resource=resource)
tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(tp)

mp = MeterProvider(
    resource=resource,
    metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())]
)
metrics.set_meter_provider(mp)

# NOW create the Sigil client
from sigil_sdk import Client
client = Client()
```

On shutdown: shut down the Sigil client (`client.shutdown()`) BEFORE shutting down the providers.

## Generation ingest pattern (LLM calls)

Every LLM call uses `client.start_generation(...)` (via the provider wrapper) and ends with `set_result(...)`. The wrapper handles most of this; what we need to ensure:

1. **`set_result` populates every available field:**
   - `response_id` (provider correlation, → `gen_ai.response.id`)
   - `response_model` (actual model used)
   - `stop_reason` / `finish_reason`
   - Full token usage including `cache_read_input_tokens`, `cache_creation_input_tokens`, `reasoning_tokens` when present

2. **Check the recorder's error state after closing:**
   ```python
   rec = client.start_generation(...)
   # ... do the LLM call, set_result, etc ...
   rec.close()
   if rec.err():
       log.error("sigil generation failed", error=rec.err())
   ```
   SDK validation / enqueue errors are silent otherwise.

3. **Set `tags` for filtering in the Sigil UI:**
   ```python
   rec = client.start_generation(
       agent_name="nc-gift-finder",
       agent_version="v1.0.0",
       conversation_id=conversation_id,
       tags={
           "app": "neoncart",
           "caller_type": caller_type,  # synthetic/interactive
           "session_id": session_id,
           "user_id": user_id,
       },
   )
   ```

4. **Set generation mode correctly:**
   - Non-stream calls: `SYNC`
   - Streaming calls: `STREAM`
   The provider wrapper picks this based on which method you call.

5. **Raw provider artifacts (full request/response bodies):** default OFF. Only enable with explicit debug opt-in (env var `SIGIL_CAPTURE_RAW_ARTIFACTS=true`).

## Workflow step pattern (SB router → specialist)

SupportBot's router makes a non-LLM decision (which specialist gets the query) before any LLM call. Capture this as a workflow step so Sigil can show the full execution graph.

```python
from sigil_sdk import WorkflowStep
from datetime import datetime, timezone

# When SB router receives a question
step = WorkflowStep(
    id=f"wfs_{uuid4().hex[:12]}",
    conversation_id=conversation_id,
    step_name="route_question",
    framework="custom",  # we hand-roll, not LangGraph
    started_at=started_at,
    completed_at=datetime.now(timezone.utc),
    input_state={"question": user_question, "user_id": user_id},
    output_state={"chosen_specialist": "sb-billing", "confidence": 0.92},
    tags={"app": "supportbot"},
    linked_generation_ids=[router_llm_generation_id],  # the LLM call that made the routing decision
    parent_step_ids=[],  # first step in the chain
    agent_name="sb-router",
    agent_version="v1.0.0",
)
client.enqueue_workflow_step(step)
```

Subsequent generations (e.g., the chosen specialist's LLM call) set `parent_generation_ids = [router_llm_generation_id]` to maintain the DAG.

## Multi-agent dependency tracking

When one specialist's output feeds another, link via `parent_generation_ids`:

```python
# nc-chatbot follows up on gift-finder's recommendations
chatbot_rec = client.start_generation(
    agent_name="nc-chatbot",
    conversation_id=conversation_id,
    parent_generation_ids=[gift_finder_generation_id],
    tags={"app": "neoncart"},
)
```

Sigil propagates eval failures: if gift-finder fails its eval, the dependent chatbot generation is flagged automatically.

## Pricing data mirror (current workaround)

Sigil computes cost server-side but doesn't emit it as a Prom metric (confirmed 2026-05-22). For Prom-queryable cost on custom dashboards, the gateway maintains a small `pricing.yaml`:

```yaml
# gateway/config/pricing.yaml
# MIRROR of Sigil's canonical pricing — TODO: remove when Sigil ships a Prom cost metric or pricing API
anthropic:
  claude-haiku-4-5-20251001:
    input_usd_per_mtoken: 1.00
    output_usd_per_mtoken: 5.00
  claude-sonnet-4-6:
    input_usd_per_mtoken: 3.00
    output_usd_per_mtoken: 15.00
openai:
  gpt-4-turbo:
    input_usd_per_mtoken: 10.00
    output_usd_per_mtoken: 30.00
gemini:
  gemini-1.5-pro:
    input_usd_per_mtoken: 1.25
    output_usd_per_mtoken: 5.00
ollama:
  default:
    output_usd_per_mtoken: 0.30
```

Gateway calculates cost from token counts × rates, emits `gen_ai.client.cost.usd`. Customer can override individual rates via env vars (e.g., `ANTHROPIC_SONNET_OUTPUT_USD_PER_MTOKEN=15.00`).

**Open feature request with Sigil eng:** add native Prom cost metric emission. When that ships, delete `pricing.yaml` and the override env vars; switch dashboards to query the Sigil-emitted metric. Single PR cleanup.

## Validation checklist

For every gateway PR that touches generation ingest:
- Span attributes emitted as expected (run gateway locally, check Tempo)
- Generation payload shape valid for Sigil's ingest contract (the SDK does this validation, but `rec.err()` must be checked)
- Token usage includes cache + reasoning fields when provider returns them
- `set_result` includes `response_id`, `response_model`, `finish_reason`
- Workflow steps emit with correct `parent_step_ids` and `linked_generation_ids`
- Multi-agent calls set `parent_generation_ids` correctly

## Useful Sigil SDK examples to copy from

In the [grafana/sigil-sdk](https://github.com/grafana/sigil-sdk) repo:
- Getting-started: `examples/getting-started/` (Python, TypeScript, Go)
- Go explicit generation flow: `go/sigil/example_test.go`
- Go provider wrappers: `go-providers/anthropic/sdk_example_test.go` (and openai/gemini variants)
- Python framework integration tests: `python-frameworks/*/tests/*.py`
- JS transport patterns: `js/test/client.transport.test.mjs`
