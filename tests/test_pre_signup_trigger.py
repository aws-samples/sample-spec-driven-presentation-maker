"""Cognito Pre sign-up trigger (infra/lambdas/pre-signup): email domain allow list."""

import importlib.util
from pathlib import Path

import pytest

_HANDLER = Path(__file__).resolve().parents[1] / "infra" / "lambdas" / "pre-signup" / "index.py"
_spec = importlib.util.spec_from_file_location("pre_signup_index", _HANDLER)
pre_signup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pre_signup)


def _event(email, trigger="PreSignUp_SignUp"):
    return {
        "triggerSource": trigger,
        "request": {"userAttributes": {"email": email}},
        "response": {"autoConfirmUser": False, "autoVerifyEmail": False, "autoVerifyPhone": False},
    }


@pytest.fixture
def domains(monkeypatch):
    def _set(value):
        monkeypatch.setenv("ALLOWED_EMAIL_DOMAINS", value)

    return _set


def test_allowed_domain_passes_the_event_through(domains):
    domains("example.com,example.org")
    event = _event("user@example.org")
    assert pre_signup.handler(event, None) is event


@pytest.mark.parametrize("email", ["user@other.com", "user@sub.example.com", "user@example.com.evil", "example.com"])
def test_other_domains_are_rejected(domains, email):
    domains("example.com")
    with pytest.raises(ValueError, match="not available"):
        pre_signup.handler(_event(email), None)


def test_match_ignores_case(domains):
    domains("Example.COM")
    event = _event("User@EXAMPLE.com")
    assert pre_signup.handler(event, None) is event


@pytest.mark.parametrize("value", ["", " , "])
def test_empty_list_rejects_everyone(domains, value):
    domains(value)
    with pytest.raises(ValueError):
        pre_signup.handler(_event("user@example.com"), None)


def test_missing_email_is_rejected(domains):
    domains("example.com")
    with pytest.raises(ValueError):
        pre_signup.handler({"triggerSource": "PreSignUp_SignUp", "request": {"userAttributes": {}}}, None)


def test_admin_created_users_are_not_checked(domains):
    domains("example.com")
    event = _event("user@other.com", trigger="PreSignUp_AdminCreateUser")
    assert pre_signup.handler(event, None) is event
