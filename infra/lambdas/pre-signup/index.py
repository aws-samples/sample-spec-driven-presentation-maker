"""Cognito Pre sign-up trigger — allow self sign-up only from the configured email domains.

ALLOWED_EMAIL_DOMAINS is a comma-separated list set by AuthStack from
`auth.allowedEmailDomains`. The match is exact and case-insensitive: `example.com`
does not admit `sub.example.com`. Users created by an administrator
(AdminCreateUser) are not checked. An empty list admits no one.
"""

import os

_ADMIN_CREATE_USER = "PreSignUp_AdminCreateUser"


def _allowed_domains() -> set[str]:
    raw = os.environ.get("ALLOWED_EMAIL_DOMAINS", "")
    return {d.strip().lower() for d in raw.split(",") if d.strip()}


def _email_domain(event: dict) -> str:
    attributes = (event.get("request") or {}).get("userAttributes") or {}
    local, at, domain = str(attributes.get("email", "")).strip().rpartition("@")
    if not at or not local:
        return ""
    return domain.lower()


def handler(event, _context):
    if event.get("triggerSource") == _ADMIN_CREATE_USER:
        return event
    domain = _email_domain(event)
    if not domain or domain not in _allowed_domains():
        # Cognito returns this message to the client as the sign-up error.
        raise ValueError("Sign-up is not available for this email address.")
    return event
