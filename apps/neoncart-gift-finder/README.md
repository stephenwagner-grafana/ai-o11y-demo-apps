# nc-gift-finder

NeonCart's AI gift-recommendation specialist. Receives a free-text gift prompt + optional budget, returns 3 product SKUs with brief explanations.

## Phase 1 status

- ✅ FastAPI shell + endpoints (`/recommend`, `/health`, `/readyz`, `/metrics`)
- 🚧 Recommendations are **stubbed** — picked at random from a hardcoded 5-product pool
- ❌ LLM gateway integration (real recommendations from Anthropic)
- ❌ Postgres catalog query for product context
- ❌ OTel + Sigil instrumentation

## Endpoint

```
POST /recommend
{
  "prompt": "birthday gift for my dad who likes gaming, budget $200",
  "session_id": "...",
  "user_id": "alice@gmail.com",
  "budget_usd": 200
}
->
{
  "ok": true,
  "specialist": "nc-gift-finder",
  "model": null,
  "recommendations": [
    {"sku": "AUD-001", "name": "...", "price_usd": 199.00, "reason": "..."},
    {"sku": "GMG-002", ...},
    {"sku": "ACC-003", ...}
  ],
  "conversation_id": "conv_..."
}
```

## Config

- `GATEWAY_URL` — LLM gateway base URL
- `POSTGRES_*` — catalog for context (Phase 2)
- Standard OTel + Sigil env vars
