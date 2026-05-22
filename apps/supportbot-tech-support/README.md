# sb-tech-support

Acme's internal "Ask Acme" bot — tech / IT specialist for employees. Receives routed questions from `sb-router` about laptops, VPN, wifi, "this app crashed", OS updates, dev tools. Phase 1 returns stubs; Phase 2 calls the LLM gateway grounded in the internal IT-runbook RAG store (pgvector in the shared Postgres).

## Endpoint

```
POST /chat
{
  "question": "my VPN doesn't connect after the OS update",
  "role": "ic",
  "employee_email": "wags.wagner@acme.com",
  "conversation_id": "..."
}
```

## Phase 1 status

- ✅ FastAPI shell + endpoints
- 🚧 Replies are stubs
- ❌ LLM gateway integration
- ❌ RAG retrieval against pgvector knowledge base
- ❌ OTel + Sigil instrumentation
