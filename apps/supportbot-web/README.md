# supportbot-web (Ask Acme)

The SupportBot ("Ask Acme") chat frontend. Acme is the fictional company; the bot answers HR / IT / payroll / benefits questions for employees.

## Look

Lifted from `ai-o11y-demo-pack/src/supportbot/frontend/html/` — clean dark purple theme, role picker (IC / Manager / HR / Finance / Legal / Exec / Contractor), per-role employee selector ("view as"), example demo verbs, single-pane chat. Separate `index.html` + `style.css` + `app.js` (no inline blob like NeonCart).

## Phase 1 status

- ✅ Static frontend renders
- ✅ Health / readiness / metrics endpoints
- 🚧 `/api/ask` endpoint is a **stub** — returns the question echoed back. Will proxy to `sb-router` → domain specialists via the LLM gateway in a later phase.
- ❌ Trace ID propagation (the "View full trace in Sigil" link in the UI is wired up but the trace_id field is null until OTel is integrated)
- ❌ Role-aware specialist routing
- ❌ Conversation history persistence

## Demo operator identity

The HTML has `${DEMO_OPERATOR_NAME}` / `${DEMO_OPERATOR_EMAIL}` placeholders for env substitution at install time. Since this app is now FastAPI-served (not nginx + envsubst), the substitution path isn't wired up — `app.js` falls back to "Wags Wagner" / "wags.wagner@acme.local". To customize: hardcode in `static/index.html` for now, or add server-side templating later.

## Local dev

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# open http://localhost:8000
```

## Docker

```bash
docker build -t supportbot-web .
docker run --rm -p 8000:8000 supportbot-web
```
