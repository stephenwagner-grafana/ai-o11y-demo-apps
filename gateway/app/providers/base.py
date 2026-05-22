"""Provider interface and shared request/response types."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderRequest:
    """Normalised request shape passed to provider.generate()."""

    messages: list[dict[str, Any]]
    model: str
    max_tokens: int = 1024
    temperature: float = 0.7
    top_p: float | None = None
    tools: list[dict[str, Any]] | None = None
    # Routing + Sigil metadata
    conversation_id: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    app: str | None = None
    agent_name: str | None = None
    agent_version: str | None = None
    caller_type: str = "synthetic"  # synthetic | interactive
    parent_generation_ids: list[str] = field(default_factory=list)


@dataclass
class ProviderResponse:
    """Normalised response shape returned by provider.generate()."""

    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    cost_usd: float = 0.0
    finish_reason: str | None = None
    response_id: str | None = None
    generation_id: str | None = None
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    reasoning_tokens: int = 0
    # Tool calls the LLM picked. Each entry: {"id", "name", "input"}.
    # Caller is responsible for executing them and feeding results back
    # in a follow-up call with role=tool messages.
    tool_calls: list[dict] = field(default_factory=list)
