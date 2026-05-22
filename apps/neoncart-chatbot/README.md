# nc-chatbot

NeonCart's general chatbot specialist. Receives `/chat` POSTs from `neoncart-web`, calls the LLM gateway, returns a reply.

## Built-in demo: "show me mice"

When the user's message contains the word **"mice"** (case-insensitive), the chatbot executes a Postgres query that references a column (`species`) that doesn't exist in our schema. Postgres returns `column "species" does not exist`, and that error bubbles through the OTel trace: browser → `nc-web` → `nc-chatbot` → `postgres`, all stitched in one trace view.

This is **intentional and always-on** — it's the signature "tada" moment of the AI o11y demo. A user typing "show me mice" in the chat widget is supposed to produce a clean, illustrative trace cascade.

Lives at `app/main.py` in the `/chat` handler. To remove or modify: change the `if "mice" in msg.lower()` branch.

When `POSTGRES_HOST` is not yet set (e.g., in the very early scaffold), the trap raises a synthetic 500 with a representative error message so traces still show something useful. Once Postgres is deployed, the trap produces a real PG error.

## Phase 1 status

- ✅ FastAPI shell + endpoints
- ✅ "Show me mice" trap wired (Postgres or synthetic fallback)
- ❌ Real Postgres connection (env vars defined; won't connect until Postgres pod exists)
- ❌ LLM gateway proxying — normal queries return a stub for now
- ❌ OTel instrumentation init (deps installed, providers not yet set up)
- ❌ Sigil generation ingest

## Config (env vars)

- `GATEWAY_URL` — base URL for the LLM gateway (e.g. `http://llm-gateway.llm-gateway.svc.cluster.local:8000`)
- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- Standard OTel + Sigil env vars (see `docs/SIGIL_INTEGRATION.md`)

## Local dev

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001

# Normal stub:
curl -X POST http://localhost:8001/chat -H 'content-type: application/json' \
  -d '{"message":"hi"}'

# Fire the mice trap:
curl -X POST http://localhost:8001/chat -H 'content-type: application/json' \
  -d '{"message":"show me mice"}'
# -> 500 with database error about column "species"
```
