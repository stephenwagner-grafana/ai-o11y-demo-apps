"""sb-tech-support tool: search_runbook.

Searches Acme's internal IT knowledge base for runbooks. Phase 1 returns
canned hits; Phase 2 does a pgvector similarity search against an
ingested runbook corpus.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


SEARCH_RUNBOOK_SCHEMA = {
    "name": "search_runbook",
    "description": (
        "Search Acme's IT knowledge base for relevant runbooks. Use when an employee "
        "asks about a specific tech problem (VPN, wifi, laptop, dev tools, etc.). "
        "Returns up to `max_results` matching runbook excerpts."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer", "default": 3, "minimum": 1, "maximum": 10},
        },
        "required": ["query"],
    },
}


_STUB_RUNBOOKS = [
    {
        "id": "rb-vpn-001",
        "title": "VPN won't connect after OS update",
        "excerpt": "If your VPN client fails to connect after an OS upgrade, first remove the existing profile and re-enrol via the IT Self-Service portal.",
    },
    {
        "id": "rb-wifi-002",
        "title": "Office WiFi auth loops",
        "excerpt": "Auth loops on the corporate SSID usually mean an expired certificate. Visit IT to refresh your 802.1X cert.",
    },
    {
        "id": "rb-laptop-003",
        "title": "Laptop returns and exchanges",
        "excerpt": "Laptops within their warranty period can be exchanged via the IT portal. Out-of-warranty repairs go through an external vendor.",
    },
]


def search_runbook(query: str, max_results: int = 3) -> dict[str, Any]:
    log.info("tool=search_runbook query=%r", query[:80])
    # Phase 1: dumb substring match against title/excerpt
    q = query.lower()
    hits = [r for r in _STUB_RUNBOOKS if q in r["title"].lower() or q in r["excerpt"].lower()] or _STUB_RUNBOOKS
    return {"ok": True, "query": query, "results": hits[:max_results]}


CREATE_TICKET_SCHEMA = {
    "name": "create_ticket",
    "description": (
        "Create an IT support ticket on behalf of the employee. Use when the runbooks "
        "don't have a clear answer and a human IT engineer needs to follow up."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "employee_email": {"type": "string", "format": "email"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "priority": {"type": "string", "enum": ["low", "normal", "high"], "default": "normal"},
        },
        "required": ["employee_email", "subject", "body"],
    },
}


def create_ticket(
    employee_email: str,
    subject: str,
    body: str,
    priority: str = "normal",
) -> dict[str, Any]:
    import uuid

    log.info("tool=create_ticket employee=%s subject=%r priority=%s",
             employee_email, subject[:60], priority)
    return {
        "ok": True,
        "ticket_id": f"IT-{uuid.uuid4().hex[:8].upper()}",
        "employee_email": employee_email,
        "subject": subject,
        "body": body,
        "priority": priority,
        "status": "open",
    }


SCHEMAS = [SEARCH_RUNBOOK_SCHEMA, CREATE_TICKET_SCHEMA]
_DISPATCH = {
    "search_runbook": search_runbook,
    "create_ticket": create_ticket,
}


def execute_tool(name: str, inputs: dict[str, Any]) -> dict[str, Any]:
    return _DISPATCH[name](**inputs)
