# sb-billing

Acme's internal "Ask Acme" bot — billing-domain specialist for employees. Receives routed questions from `sb-router` about expense reports, corporate-card charges, employee reimbursements, payroll deductions. Phase 1 returns stubs; Phase 2 calls the LLM gateway with billing-domain context.

## Endpoint

```
POST /chat
{
  "question": "why was I charged twice for my laptop?",
  "role": "ic",
  "employee_email": "wags.wagner@acme.com",
  "conversation_id": "..."
}
```

## Phase 1 status

- ✅ FastAPI shell + endpoints
- 🚧 Replies are stubs
- ❌ LLM gateway integration
- ❌ Billing context retrieval (recent invoices, payment methods, refund policy)
- ❌ OTel + Sigil instrumentation
