"""LLM provider wrappers.

Each provider module exposes a single `generate(request)` coroutine
that calls the upstream provider via the Sigil SDK's provider wrapper
when one exists, or hand-rolls instrumentation when it doesn't.

Provider implementations:
- anthropic.py  : sigil-sdk-anthropic wrapper (real)
- openai.py     : sigil-sdk-openai wrapper (real once installed)
- gemini.py     : sigil-sdk-gemini wrapper (real once installed)
- ollama.py     : hand-rolled (no Sigil wrapper exists for Ollama)
"""
from .base import ProviderRequest, ProviderResponse  # re-export
