"""Sigil SDK client lifecycle.

The Sigil SDK reads its config from SIGIL_* env vars (see docs/SIGIL_INTEGRATION.md):
    SIGIL_ENDPOINT
    SIGIL_PROTOCOL
    SIGIL_AUTH_MODE
    SIGIL_AUTH_TENANT_ID
    SIGIL_AUTH_TOKEN

OTel providers must be initialised BEFORE the Sigil client is created
(otherwise SDK telemetry goes to no-op and is silently lost).
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)

_client: Any = None


def init_sigil() -> Any:
    """Create the Sigil client (idempotent).

    Returns the client. If SIGIL_* env vars are not set, logs a warning
    and returns None — the gateway will still run but generations won't
    be recorded.
    """
    global _client
    if _client is not None:
        return _client

    if not os.getenv("SIGIL_AUTH_TOKEN"):
        log.warning("SIGIL_AUTH_TOKEN not set — Sigil client not initialised. Generations will NOT be recorded.")
        return None

    try:
        from sigil_sdk import Client
    except ImportError:
        log.error("sigil-sdk not installed — pip install sigil-sdk")
        return None

    _client = Client()  # reads SIGIL_* env vars internally
    log.info("Sigil client initialised (endpoint=%s)", os.getenv("SIGIL_ENDPOINT", "<unset>"))
    return _client


def get_sigil() -> Any:
    """Return the initialised client, or None if not available."""
    return _client


def shutdown_sigil() -> None:
    """Flush + shut down the Sigil client. Call on app teardown BEFORE OTel shutdown."""
    global _client
    if _client is None:
        return
    try:
        _client.shutdown()
    except Exception as e:
        log.warning("Sigil client shutdown failed: %s", e)
    finally:
        _client = None
