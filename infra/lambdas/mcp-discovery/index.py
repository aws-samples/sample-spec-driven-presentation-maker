"""OAuth 2.1 discovery + MCP proxy for external MCP clients.

Routes:
- GET  /.well-known/oauth-protected-resource
- GET  /.well-known/oauth-authorization-server
- POST /register                  (RFC 7591 Dynamic Client Registration)
- GET  /authorize                 (proxy to Cognito with scope injection)
- POST /token                     (proxy to Cognito token endpoint)
- ANY  / or /mcp                  (Bearer auth required, proxied to AgentCore)
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

import boto3

COGNITO_DOMAIN = os.environ["COGNITO_DOMAIN"]
ISSUER = os.environ["ISSUER"]
RUNTIME_URL = os.environ["RUNTIME_URL"]
USER_POOL_ID = os.environ["USER_POOL_ID"]
MCP_SCOPES = [s for s in os.environ.get("MCP_SCOPES", "openid,profile,email").split(",") if s]


def handler(event, context):
    path = event.get("rawPath", "")
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    base_url = f"https://{event['requestContext']['domainName']}"
    qs = event.get("rawQueryString", "")

    if path == "/.well-known/oauth-protected-resource":
        return _json(200, {
            "resource": base_url,
            "authorization_servers": [base_url],
            "scopes_supported": MCP_SCOPES,
            "bearer_methods_supported": ["header"],
            "resource_name": "spec-driven-presentation-maker MCP Server",
        })

    if path == "/.well-known/oauth-authorization-server":
        return _json(200, {
            "issuer": ISSUER,
            "authorization_endpoint": f"{base_url}/authorize",
            "token_endpoint": f"{base_url}/token",
            "userinfo_endpoint": f"{COGNITO_DOMAIN}/oauth2/userInfo",
            "jwks_uri": f"{ISSUER}/.well-known/jwks.json",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": MCP_SCOPES,
            "token_endpoint_auth_methods_supported": ["none"],
            "registration_endpoint": f"{base_url}/register",
        })

    # RFC 7591 Dynamic Client Registration — creates a Cognito App Client
    if path == "/register" and method == "POST":
        reg = json.loads(_body(event) or "{}")
        client_name = reg.get("client_name", "mcp-dynamic-client")[:64]
        redirect_uris = reg.get("redirect_uris", [])
        if not redirect_uris:
            return _json(400, {"error": "invalid_client_metadata",
                               "error_description": "redirect_uris required"})
        resp = boto3.client("cognito-idp").create_user_pool_client(
            UserPoolId=USER_POOL_ID, ClientName=f"dcr-{client_name}",
            GenerateSecret=False,
            AllowedOAuthFlows=["code"], AllowedOAuthFlowsUserPoolClient=True,
            AllowedOAuthScopes=MCP_SCOPES,
            CallbackURLs=redirect_uris, LogoutURLs=redirect_uris,
            SupportedIdentityProviders=["COGNITO"],
        )
        return _json(201, {
            "client_id": resp["UserPoolClient"]["ClientId"],
            "client_name": client_name,
            "redirect_uris": redirect_uris,
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        })

    # Inject MCP_SCOPES into scope param so clients that omit it
    # (e.g. Kiro / Q DEV CLI) still get tokens with the custom scope.
    # Also serves Claude.ai which appends /authorize to the MCP server URL.
    if path == "/authorize" and method == "GET":
        params = urllib.parse.parse_qs(qs, keep_blank_values=True)
        scopes = set(params.get("scope", [" ".join(MCP_SCOPES)])[0].split())
        scopes.update(MCP_SCOPES)
        params["scope"] = [" ".join(sorted(scopes))]
        new_qs = urllib.parse.urlencode(params, doseq=True)
        return {"statusCode": 302,
                "headers": {"Location": f"{COGNITO_DOMAIN}/oauth2/authorize?{new_qs}"}}

    if path == "/token" and method == "POST":
        body = _body(event)
        headers = {"Content-Type": event.get("headers", {}).get(
            "content-type", "application/x-www-form-urlencoded")}
        req = urllib.request.Request(
            f"{COGNITO_DOMAIN}/oauth2/token", data=body.encode(),
            headers=headers, method="POST")
        try:
            r = urllib.request.urlopen(req)  # nosec B310 - fixed Cognito endpoint
            return {"statusCode": r.status,
                    "headers": {"Content-Type": r.headers.get("Content-Type", "application/json")},
                    "body": r.read().decode()}
        except urllib.error.HTTPError as e:
            return {"statusCode": e.code,
                    "headers": {"Content-Type": "application/json"},
                    "body": e.read().decode()}

    # MCP endpoint — validate Bearer then proxy to AgentCore Runtime
    if path in ("/mcp", "/"):
        auth = event.get("headers", {}).get("authorization", "")
        if not auth.startswith("Bearer "):
            return _unauthorized(base_url, "unauthorized")
        body = _body(event)
        req = urllib.request.Request(
            RUNTIME_URL, data=body.encode() if body else None,
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream",
                     "Authorization": auth}, method="POST")
        try:
            r = urllib.request.urlopen(req)  # nosec B310 - fixed AgentCore endpoint
            return {"statusCode": r.status,
                    "headers": {"Content-Type": r.headers.get("Content-Type", "application/json")},
                    "body": r.read().decode()}
        except urllib.error.HTTPError as e:
            # On upstream 401, return WWW-Authenticate so clients re-run OAuth.
            if e.code == 401:
                return _unauthorized(base_url, "invalid_token")
            return {"statusCode": e.code,
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps({"error": "upstream_error", "status": e.code})}

    return _json(404, {"error": "not found"})


def _body(event):
    body = event.get("body", "") or ""
    if event.get("isBase64Encoded"):
        import base64
        body = base64.b64decode(body).decode()
    return body


def _json(code, body):
    return {"statusCode": code,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body)}


def _unauthorized(base_url, error):
    return {"statusCode": 401,
            "headers": {"WWW-Authenticate":
                        f'Bearer resource_metadata="{base_url}/.well-known/oauth-protected-resource"'},
            "body": json.dumps({"error": error})}
