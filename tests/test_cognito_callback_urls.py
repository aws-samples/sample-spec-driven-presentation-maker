"""WebClient callback/logout URL custom resource (infra/lambdas/cognito-callback-urls).

The handler sets the URLs to exactly the dev URL and the site URL WebUiStack
publishes in SSM, whichever custom resource calls it. UpdateUserPoolClient
resets every field it is not given, so the handler must send back the
WebClient's current settings — above all AllowedOAuthScopes with
sdpm-mcp/invoke — and change only the callback and logout URLs.
"""

import importlib.util
import os
from pathlib import Path

import pytest
from botocore.stub import Stubber

_HANDLER = Path(__file__).resolve().parents[1] / "infra" / "lambdas" / "cognito-callback-urls" / "index.py"

_PARAM = "/sdpm/web-ui/site-url"
_SITE = "https://d111abc.cloudfront.net"
_URLS = ["http://localhost:3000", _SITE]


@pytest.fixture
def mod(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", os.environ.get("AWS_DEFAULT_REGION", "ap-northeast-1"))
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("USER_POOL_ID", "ap-northeast-1_pool")
    monkeypatch.setenv("CLIENT_ID", "client123")
    monkeypatch.setenv("DEV_URL", "http://localhost:3000")
    monkeypatch.setenv("SITE_URL_PARAM", _PARAM)
    spec = importlib.util.spec_from_file_location("cognito_callback_urls_index", _HANDLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# DescribeUserPoolClient output shaped like the deployed WebClient right after
# CloudFormation applied AuthStack's template (dev URL only).
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

_CLIENT_KEY = {"UserPoolId": "ap-northeast-1_pool", "ClientId": "client123"}


def _event(request_type, logical_id="WebClientUrls", properties=None):
    return {
        "RequestType": request_type,
        "ResponseURL": "https://cloudformation-custom-resource-response.example/abc",
        "StackId": "stack",
        "RequestId": "req",
        "LogicalResourceId": logical_id,
        "ResourceProperties": {
            "ServiceToken": "arn:aws:lambda:ap-northeast-1:111122223333:function:fn",
            **(properties or {"ClientConfigHash": "abc"}),
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


def _site_url(stub, value=_SITE):
    stub.add_response("get_parameter", {"Parameter": {"Name": _PARAM, "Value": value}}, {"Name": _PARAM})


@pytest.mark.parametrize("request_type", ["Create", "Update"])
@pytest.mark.parametrize("event", [
    # AuthStack, after CloudFormation updated the client.
    lambda t: _event(t, "WebClientUrls", {"ClientConfigHash": "abc"}),
    # WebUiStack, after its site URL was created or changed.
    lambda t: _event(t, "WebClientUrls", {"SiteUrl": _SITE}),
])
def test_the_urls_become_the_dev_url_and_the_published_site_url(mod, monkeypatch, request_type, event):
    sent = _capture_send(mod, monkeypatch)
    with Stubber(mod.ssm) as ssm_stub, Stubber(mod.cognito) as stub:
        _site_url(ssm_stub)
        stub.add_response("describe_user_pool_client", {"UserPoolClient": _CURRENT}, _CLIENT_KEY)
        # Stubber checks the exact parameters, and validates them against the API model.
        stub.add_response("update_user_pool_client", {"UserPoolClient": {}}, _expected_update())
        mod.handler(event(request_type), _Context())
        stub.assert_no_pending_responses()
        ssm_stub.assert_no_pending_responses()
    assert sent == [("SUCCESS", "web-client-urls:client123", None)]


def test_other_urls_on_the_client_are_dropped(mod, monkeypatch):
    sent = _capture_send(mod, monkeypatch)
    extra = ["http://localhost:3000", "https://evil.example", _SITE]
    current = {**_CURRENT, "CallbackURLs": extra, "LogoutURLs": extra}
    with Stubber(mod.ssm) as ssm_stub, Stubber(mod.cognito) as stub:
        _site_url(ssm_stub)
        stub.add_response("describe_user_pool_client", {"UserPoolClient": current}, _CLIENT_KEY)
        stub.add_response("update_user_pool_client", {"UserPoolClient": {}}, _expected_update())
        mod.handler(_event("Update"), _Context())
        stub.assert_no_pending_responses()
    assert sent[0][0] == "SUCCESS"


def test_a_client_that_already_has_the_urls_is_not_updated(mod, monkeypatch):
    sent = _capture_send(mod, monkeypatch)
    current = {**_CURRENT, "CallbackURLs": _URLS, "LogoutURLs": _URLS}
    with Stubber(mod.ssm) as ssm_stub, Stubber(mod.cognito) as stub:
        _site_url(ssm_stub)
        stub.add_response("describe_user_pool_client", {"UserPoolClient": current}, _CLIENT_KEY)
        mod.handler(_event("Update"), _Context())
        stub.assert_no_pending_responses()
    assert sent == [("SUCCESS", "web-client-urls:client123", None)]


def test_without_a_published_site_url_the_client_is_left_alone(mod, monkeypatch):
    # AuthStack deployed before WebUiStack: nothing to add.
    sent = _capture_send(mod, monkeypatch)
    with Stubber(mod.ssm) as ssm_stub, Stubber(mod.cognito) as stub:
        ssm_stub.add_client_error("get_parameter", "ParameterNotFound", "missing")
        mod.handler(_event("Create"), _Context())
        stub.assert_no_pending_responses()
    assert sent == [("SUCCESS", "web-client-urls:client123", None)]


@pytest.mark.parametrize("value", [
    "https://evil.example",
    "http://d111abc.cloudfront.net",
    "https://d111abc.cloudfront.net/",
    "https://d111abc.cloudfront.net.evil.example",
    "https://x.d111abc.cloudfront.net",
])
def test_a_published_value_that_is_not_a_cloudfront_site_url_fails(mod, monkeypatch, value):
    sent = _capture_send(mod, monkeypatch)
    with Stubber(mod.ssm) as ssm_stub, Stubber(mod.cognito) as stub:
        _site_url(ssm_stub, value)
        mod.handler(_event("Update"), _Context())
        stub.assert_no_pending_responses()
    assert sent[0][0] == "FAILED"
    assert "not a CloudFront site URL" in sent[0][2]


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
    with Stubber(mod.ssm) as ssm_stub, Stubber(mod.cognito) as stub:
        mod.handler(_event("Delete"), _Context())
        stub.assert_no_pending_responses()
        ssm_stub.assert_no_pending_responses()
    assert sent == [("SUCCESS", "web-client-urls:client123", None)]


def test_an_api_error_fails_the_resource(mod, monkeypatch):
    sent = _capture_send(mod, monkeypatch)
    with Stubber(mod.ssm) as ssm_stub, Stubber(mod.cognito) as stub:
        _site_url(ssm_stub)
        stub.add_client_error("describe_user_pool_client", "ResourceNotFoundException", "no such client")
        mod.handler(_event("Update"), _Context())
    assert sent[0][0] == "FAILED"
    assert "no such client" in sent[0][2]
