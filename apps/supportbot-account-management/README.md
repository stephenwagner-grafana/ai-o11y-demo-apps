# sb-account-management

Acme support bot account / profile / IAM specialist. Receives routed questions from `sb-router` about passwords, login issues, profile updates, role/permission changes. Phase 1 returns stubs; Phase 2 calls the LLM gateway with HR/IAM policy context.

## Endpoint

```
POST /chat
{
  "question": "how do I change my email address on file?",
  "role": "ic",
  "employee_email": "wags.wagner@acme.com",
  "conversation_id": "..."
}
```

## Phase 1 status

- ✅ FastAPI shell + endpoints
- 🚧 Replies are stubs
- ❌ LLM gateway integration
- ❌ Policy/IAM context retrieval
- ❌ OTel + Sigil instrumentation
