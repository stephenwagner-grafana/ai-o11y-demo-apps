# sb-router

SupportBot's routing specialist. Receives an Acme-employee question, decides which domain specialist should handle it, and forwards it.

## Phase 1 status

- ✅ FastAPI shell + endpoints
- ✅ Keyword-based routing (case-insensitive substring match across `billing` / `tech-support` / `account-management` / `unable-to-route`)
- ✅ Downstream HTTP forwarding to domain specialists via in-cluster service URLs
- ❌ LLM-based classification (Phase 2 will swap keywords for a gateway call)
- ❌ Sigil workflow-step ingest — the routing decision should be captured as a workflow step (`step_name="route_question"`, `input_state={question, role}`, `output_state={chosen_specialist}`, `linked_generation_ids=[…]`)

## Endpoint

```
POST /ask
{
  "question": "why was I charged twice for my laptop?",
  "role": "ic",
  "employee_email": "wags.wagner@acme.com",
  "conversation_id": "..."
}
->
{
  "ok": true,
  "specialist": "sb-router",
  "domain": "billing",
  "reply": "...",            # from sb-billing
  "downstream_specialist": "sb-billing",
  "model": null,
  "conversation_id": "..."
}
```

## Config

- `SB_BILLING_URL` (default `http://sb-billing.support-bot.svc.cluster.local:8000`)
- `SB_TECH_SUPPORT_URL` (default `http://sb-tech-support.support-bot.svc.cluster.local:8000`)
- `SB_ACCOUNT_URL` (default `http://sb-account-management.support-bot.svc.cluster.local:8000`)
- Standard OTel + Sigil env vars
