"""sb-billing tool: lookup_employee_expense.

Looks up an employee's expense report / corp-card charges. Phase 1 returns
canned data; Phase 2 reads from a real expense system (or Postgres mock).
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


LOOKUP_EMPLOYEE_EXPENSE_SCHEMA = {
    "name": "lookup_employee_expense",
    "description": (
        "Look up an Acme employee's recent expense report and corp-card charges. "
        "Use when an employee asks about a specific charge, reimbursement, or balance."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "employee_email": {"type": "string", "format": "email"},
            "period": {
                "type": "string",
                "enum": ["last-30-days", "last-90-days", "this-quarter"],
                "default": "last-30-days",
            },
        },
        "required": ["employee_email"],
    },
}


def lookup_employee_expense(employee_email: str, period: str = "last-30-days") -> dict[str, Any]:
    log.info("tool=lookup_employee_expense employee=%s period=%s", employee_email, period)
    return {
        "ok": True,
        "employee_email": employee_email,
        "period": period,
        "total_usd": 1247.32,
        "charges": [
            {"date": "2026-05-20", "amount_usd": 42.50, "merchant": "Coffee Co",     "category": "meals"},
            {"date": "2026-05-15", "amount_usd": 285.00, "merchant": "Acme Travel",  "category": "travel"},
            {"date": "2026-05-10", "amount_usd": 919.82, "merchant": "Apple Store",  "category": "equipment"},
        ],
    }


SUBMIT_REIMBURSEMENT_SCHEMA = {
    "name": "submit_reimbursement_request",
    "description": (
        "Submit a reimbursement request on behalf of the employee. Use when the employee "
        "has paid out of pocket and wants the expense reimbursed. Returns a ticket ID."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "employee_email": {"type": "string", "format": "email"},
            "amount_usd": {"type": "number", "minimum": 0},
            "merchant": {"type": "string"},
            "category": {"type": "string"},
            "note": {"type": "string"},
        },
        "required": ["employee_email", "amount_usd", "merchant"],
    },
}


def submit_reimbursement_request(
    employee_email: str,
    amount_usd: float,
    merchant: str,
    category: str = "other",
    note: str | None = None,
) -> dict[str, Any]:
    import uuid

    log.info("tool=submit_reimbursement_request employee=%s amount=$%.2f", employee_email, amount_usd)
    return {
        "ok": True,
        "ticket_id": f"REIM-{uuid.uuid4().hex[:8].upper()}",
        "employee_email": employee_email,
        "amount_usd": amount_usd,
        "merchant": merchant,
        "category": category,
        "note": note,
        "status": "submitted",
    }


SCHEMAS = [LOOKUP_EMPLOYEE_EXPENSE_SCHEMA, SUBMIT_REIMBURSEMENT_SCHEMA]
_DISPATCH = {
    "lookup_employee_expense": lookup_employee_expense,
    "submit_reimbursement_request": submit_reimbursement_request,
}


def execute_tool(name: str, inputs: dict[str, Any]) -> dict[str, Any]:
    return _DISPATCH[name](**inputs)
