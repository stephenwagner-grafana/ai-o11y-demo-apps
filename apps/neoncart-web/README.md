# neoncart-web

The NeonCart e-commerce storefront. Serves the static HTML/CSS/JS frontend and proxies AI requests to the `nc-chatbot` and `nc-gift-finder` specialists (which in turn call the LLM gateway).

## Look

The UI is lifted from `ai-o11y-demo-pack/src/neoncart/code/storefront.js` — neon cyberpunk theme with custom CSS variables, Google fonts (Audiowide / Monoton / Inter / JetBrains Mono), radial gradients, sticky header with backdrop blur, category pills, hero, trending rail, gift-finder modal, chatbot overlay.

All inline HTML+CSS+JS was extracted into a single `static/index.html` (3815 lines). No build step. The JS makes fetch() calls to the API endpoints listed in `app/main.py`.

## Phase 1 status

- ✅ Static frontend renders
- ✅ Health / readiness / metrics endpoints
- 🚧 API endpoints are **stubs** — return sensible JSON shapes so the JS doesn't error, but no real data yet
- ❌ Postgres integration
- ❌ Specialist proxying (`nc-chatbot`, `nc-gift-finder`)
- ❌ OTel auto-instrumentation wired up
- ❌ Sigil span attributes on browser sessions

Next phases will replace each stub with a real implementation.

## Local dev

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# open http://localhost:8000
```

## Docker

```bash
docker build -t neoncart-web .
docker run --rm -p 8000:8000 neoncart-web
```
