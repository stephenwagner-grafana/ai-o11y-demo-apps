"""sb-account-management tool: lookup_employee_profile."""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


LOOKUP_EMPLOYEE_PROFILE_SCHEMA = {
    "name": "lookup_employee_profile",
    "description": (
        "Look up an Acme employee's profile (role, manager, groups, SSO status). "
        "Use when an employee asks about their account, login, or group membership."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "employee_email": {"type": "string", "format": "email"},
        },
        "required": ["employee_email"],
    },
}


def lookup_employee_profile(employee_email: str) -> dict[str, Any]:
    log.info("tool=lookup_employee_profile employee=%s", employee_email)
    return {
        "ok": True,
        "employee_email": employee_email,
        "display_name": employee_email.split("@", 1)[0].replace(".", " ").title(),
        "role": "Individual Contributor",
        "manager": "aisha.rahman@acme.com",
        "groups": ["all-employees", "engineering", "acme-vpn-users"],
        "sso_enabled": True,
        "last_password_change": "2026-04-12",
    }


REQUEST_PASSWORD_RESET_SCHEMA = {
    "name": "request_password_reset",
    "description": (
        "Initiate an SSO password reset for an employee. Sends a reset link to the "
        "employee's secondary recovery address. Returns the request ID."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "employee_email": {"type": "string", "format": "email"},
        },
        "required": ["employee_email"],
    },
}


def request_password_reset(employee_email: str) -> dict[str, Any]:
    import uuid

    log.info("tool=request_password_reset employee=%s", employee_email)
    return {
        "ok": True,
        "request_id": f"PWR-{uuid.uuid4().hex[:8].upper()}",
        "employee_email": employee_email,
        "status": "reset_link_sent",
        "expires_in_minutes": 30,
    }


SCHEMAS = [LOOKUP_EMPLOYEE_PROFILE_SCHEMA, REQUEST_PASSWORD_RESET_SCHEMA]
_DISPATCH = {
    "lookup_employee_profile": lookup_employee_profile,
    "request_password_reset": request_password_reset,
}


def execute_tool(name: str, inputs: dict[str, Any]) -> dict[str, Any]:
    return _DISPATCH[name](**inputs)
