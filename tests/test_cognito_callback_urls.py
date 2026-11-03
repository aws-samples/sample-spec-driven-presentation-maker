"""Cognito callback URL custom resource (infra/lambdas/cognito-callback-urls).

UpdateUserPoolClient resets every field it is not given. The handler must send
back the WebClient's current settings — above all AllowedOAuthScopes with
sdpm-mcp/invoke — and change only the callback and logout URLs.
"""

import importlib.util
import os
from pathlib import Path

import pytest
from botocore.stub import Stubber

_HANDLER = Path(__file__).resolve().parents[1] / "infra" / "lambdas" / "cognito-callback-urls" / "index.py"


@pytest.fixture
def mod(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", os.environ.get("AWS_DEFAULT_REGION", "ap-northeast-1"))
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    spec = importlib.util.spec_from_file_location("cognito_callback_urls_index", _HANDLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# DescribeUserPoolClient output shaped like the deployed WebClient after AuthStack set it.
_CURRENT = {
    "UserPoolId": "ap-northeast-1_pool",
    "ClientName": "UserPoolWebClient4C9370B0-abc",
    "ClientId": "client123",
    "LastModifiedDate": "2026-05-06T08:39:41Z",
    "CreationDate": "2026-04-06T05:12:08Z",
    "RefreshTokenValidity": 30,
    "TokenValidityUnits": {},
    "ExplicitAuthFlows": ["ALLOW_REFRESH_TOKEN_AUTH", "ALLOW_USER_PASSWORD_AUTH", "ALLOW_USER_SRP_AUTH"],
    "SupportedIdentityProviders": ["COGNITO"],
    "CallbackURLs": ["http://localhost:3000"],
    "LogoutURLs": ["http://localhost:3000"],
    "AllowedOAuthFlows": ["code"],
    "AllowedOAuthScopes": ["email", "openid", "profile", "sdpm-mcp/invoke"],
    "AllowedOAuthFlowsUserPoolClient": True,
    "EnableTokenRevocation": True,
    "EnablePropagateAdditionalUserContextData": False,
    "AuthSessionValidity": 3,
}
_URLS = ["http://localhost:3000", "https://d111.cloudfront.net"]


def _event(request_type):
    return {
        "RequestType": request_type,
        "ResponseURL": "https://cloudformation-custom-resource-response.example/abc",
        "StackId": "stack",
        "RequestId": "req",
        "LogicalResourceId": "UpdateCognitoCallbackUrls",
        "ResourceProperties": {
            "ServiceToken": "arn:aws:lambda:ap-northeast-1:111122223333:function:fn",
            "UserPoolId": "ap-northeast-1_pool",
            "ClientId": "client123",
            "CallbackURLs": _URLS,
            "LogoutURLs": _URLS,
        },
    }


class _Context:
    log_stream_name = "stream"


def _capture_send(module, monkeypatch):
    sent = []
    monkeypatch.setattr(module, "send", lambda event, context, status, physical_id, reason=None: sent.append(
        (status, physical_id, reason)))
    return sent


def _expected_update():
    read_only = {"LastModifiedDate", "CreationDate"}
    expected = {k: v for k, v in _CURRENT.items() if k not in read_only}
    expected["CallbackURLs"] = _URLS
    expected["LogoutURLs"] = _URLS
    return expected


@pytest.mark.parametrize("request_type", ["Create", "Update"])
def test_only_the_urls_change_and_every_other_field_is_sent_back(mod, monkeypatch, request_type):
    sent = _capture_send(mod, monkeypatch)
    with Stubber(mod.cognito) as stub:
        stub.add_response(
            "describe_user_pool_client",
            {"UserPoolClient": _CURRENT},
            {"UserPoolId": "ap-northeast-1_pool", "ClientId": "client123"},
        )
        # Stubber checks the exact parameters, and validates them against the API model.
        stub.add_response("update_user_pool_client", {"UserPoolClient": {}}, _expected_update())
        mod.handler(_event(request_type), _Context())
        stub.assert_no_pending_responses()
    assert sent == [("SUCCESS", "cognito-callback-urls:client123", None)]


def test_the_update_keeps_the_mcp_scope(mod):
    fields = set(mod.cognito.meta.service_model.operation_model("UpdateUserPoolClient").input_shape.members)
    request = mod.update_request(_CURRENT, _URLS, _URLS, fields)
    assert request["AllowedOAuthScopes"] == ["email", "openid", "profile", "sdpm-mcp/invoke"]
    assert request["AllowedOAuthFlows"] == ["code"]
    assert request["ExplicitAuthFlows"] == _CURRENT["ExplicitAuthFlows"]
    assert "ClientSecret" not in request and "CreationDate" not in request


def test_read_only_fields_are_dropped(mod):
    request = mod.update_request({**_CURRENT, "ClientSecret": "s"}, _URLS, _URLS, {"UserPoolId", "ClientId"})
    assert request == {"UserPoolId": "ap-northeast-1_pool", "ClientId": "client123",
                       "CallbackURLs": _URLS, "LogoutURLs": _URLS}


def test_delete_leaves_the_client_alone(mod, monkeypatch):
    sent = _capture_send(mod, monkeypatch)
    with Stubber(mod.cognito) as stub:
        mod.handler(_event("Delete"), _Context())
        stub.assert_no_pending_responses()
    assert sent == [("SUCCESS", "cognito-callback-urls:client123", None)]


def test_an_api_error_fails_the_resource(mod, monkeypatch):
    sent = _capture_send(mod, monkeypatch)
    with Stubber(mod.cognito) as stub:
        stub.add_client_error("describe_user_pool_client", "ResourceNotFoundException", "no such client")
        mod.handler(_event("Update"), _Context())
    assert sent[0][0] == "FAILED"
    assert "no such client" in sent[0][2]
