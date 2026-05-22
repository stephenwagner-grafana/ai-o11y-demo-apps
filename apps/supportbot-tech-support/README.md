# sb-tech-support

Acme support bot tech / IT specialist. Receives routed questions from `sb-router` about hardware, software, network, VPN, "doesn't work" issues. Phase 1 returns stubs; Phase 2 calls the LLM gateway grounded in the RAG knowledge base (pgvector in the shared Postgres).

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
