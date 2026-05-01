"""OAuth 2.1 discovery + MCP proxy for external MCP clients.

Routes:
- GET  /.well-known/oauth-protected-resource
- GET  /.well-known/oauth-authorization-server
- POST /register                  (RFC 7591 Dynamic Client Registration)
- GET  /authorize                 (proxy to Cognito with scope injection)
- POST /token                     (proxy to Cognito token endpoint)
- ANY  / or /mcp                  (Bearer auth required, proxied to AgentCore)

Uses urllib3 (not urllib.request) for upstream HTTP calls so the library only
speaks HTTP/HTTPS, eliminating the file:// scheme exposure that urllib.request
allows. urllib3 ships with the Lambda Python runtime via boto3, so no extra
package install is needed.
"""

import json
import os
import urllib.parse

import boto3
import urllib3

COGNITO_DOMAIN = os.environ["COGNITO_DOMAIN"]
ISSUER = os.environ["ISSUER"]
RUNTIME_URL = os.environ["RUNTIME_URL"]
USER_POOL_ID = os.environ["USER_POOL_ID"]
MCP_SCOPES = [s for s in os.environ.get("MCP_SCOPES", "openid,profile,email").split(",") if s]
ENABLE_DCR = os.environ.get("ENABLE_DCR", "true").lower() == "true"

# Upstream HTTP client. Lambda timeout is 30s, so leave some headroom for
# handler overhead. connect timeout is short enough to surface unreachable
# endpoints quickly without cutting slow-but-valid responses.
_UPSTREAM_TIMEOUT = urllib3.Timeout(connect=5.0, read=25.0)
_http = urllib3.PoolManager(timeout=_UPSTREAM_TIMEOUT)


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
        metadata = {
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
        }
        if ENABLE_DCR:
            metadata["registration_endpoint"] = f"{base_url}/register"
        return _json(200, metadata)

    # RFC 7591 Dynamic Client Registration — idempotent by client_name.
    # If a client with the same name already exists, merge redirect_uris
    # and return the existing client_id instead of creating a new one.
    if path == "/register" and method == "POST":
        if not ENABLE_DCR:
            return _json(403, {"error": "registration_not_supported",
                               "error_description": "Dynamic client registration is disabled"})
        reg = json.loads(_body(event) or "{}")
        client_name = reg.get("client_name", "mcp-dynamic-client")[:64]
        redirect_uris = reg.get("redirect_uris", [])
        if not redirect_uris:
            return _json(400, {"error": "invalid_client_metadata",
                               "error_description": "redirect_uris required"})
        cognito = boto3.client("cognito-idp")
        full_name = f"dcr-{client_name}"
        existing = _find_dcr_client(cognito, full_name)
        if existing:
            cur = existing.get("CallbackURLs", [])
            merged = list(dict.fromkeys(cur + redirect_uris))
            if len(merged) > 95:
                merged = merged[-95:]
            cognito.update_user_pool_client(
                UserPoolId=USER_POOL_ID,
                ClientId=existing["ClientId"],
                ClientName=full_name,
                AllowedOAuthFlows=["code"], AllowedOAuthFlowsUserPoolClient=True,
                AllowedOAuthScopes=MCP_SCOPES,
                CallbackURLs=merged, LogoutURLs=merged,
                SupportedIdentityProviders=["COGNITO"],
            )
            return _json(200, {
                "client_id": existing["ClientId"],
                "client_name": client_name,
                "redirect_uris": merged,
                "grant_types": ["authorization_code"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            })
        resp = cognito.create_user_pool_client(
            UserPoolId=USER_POOL_ID, ClientName=full_name,
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
        # Ensure redirect_uri is registered on the app client.
        # UpdateUserPoolClient in /register may not have propagated yet,
        # so we patch the client again here as a safety net.
        redirect_uri = params.get("redirect_uri", [None])[0]
        client_id = params.get("client_id", [None])[0]
        if redirect_uri and client_id:
            _ensure_callback_url(client_id, redirect_uri)
        new_qs = urllib.parse.urlencode(params, doseq=True)
        return {"statusCode": 302,
                "headers": {"Location": f"{COGNITO_DOMAIN}/oauth2/authorize?{new_qs}"}}

    if path == "/token" and method == "POST":
        body = _body(event)
        r = _http.request(
            "POST",
            f"{COGNITO_DOMAIN}/oauth2/token",
            body=body.encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        return {"statusCode": r.status,
                "headers": {"Content-Type": r.headers.get("Content-Type", "application/json")},
                "body": r.data.decode()}

    # MCP endpoint — validate Bearer then proxy to AgentCore Runtime
    if path in ("/mcp", "/"):
        auth = event.get("headers", {}).get("authorization", "")
        if not auth.startswith("Bearer "):
            return _unauthorized(base_url, "unauthorized")
        body = _body(event)
        r = _http.request(
            "POST",
            RUNTIME_URL,
            body=body.encode() if body else None,
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream",
                     "Authorization": auth},
        )
        if r.status == 401:
            return _unauthorized(base_url, "invalid_token")
        if r.status >= 400:
            return {"statusCode": r.status,
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps({"error": "upstream_error", "status": r.status})}
        return {"statusCode": r.status,
                "headers": {"Content-Type": r.headers.get("Content-Type", "application/json")},
                "body": r.data.decode()}

    return _json(404, {"error": "not found"})


def _find_dcr_client(cognito, full_name):
    """Find an existing Cognito app client by ClientName (paginated)."""
    paginator = cognito.get_paginator("list_user_pool_clients")
    for page in paginator.paginate(UserPoolId=USER_POOL_ID, MaxResults=60):
        for c in page.get("UserPoolClients", []):
            if c.get("ClientName") == full_name:
                return cognito.describe_user_pool_client(
                    UserPoolId=USER_POOL_ID, ClientId=c["ClientId"],
                )["UserPoolClient"]
    return None


def _ensure_callback_url(client_id, redirect_uri):
    """Add redirect_uri to a DCR app client's CallbackURLs if missing.

    Only applies to dynamically registered clients (dcr-* prefix).
    Static clients must have their callback URLs pre-registered via
    config.yaml mcpCallbackUrls — allowing dynamic additions would
    bypass the redirect_uri validation that OAuth relies on.
    """
    try:
        cognito = boto3.client("cognito-idp")
        resp = cognito.describe_user_pool_client(
            UserPoolId=USER_POOL_ID, ClientId=client_id,
        )["UserPoolClient"]
        if not resp.get("ClientName", "").startswith("dcr-"):
            return
        urls = resp.get("CallbackURLs", [])
        if redirect_uri in urls:
            return
        urls.append(redirect_uri)
        if len(urls) > 95:
            urls = urls[-95:]
        cognito.update_user_pool_client(
            UserPoolId=USER_POOL_ID,
            ClientId=client_id,
            ClientName=resp["ClientName"],
            AllowedOAuthFlows=resp.get("AllowedOAuthFlows", ["code"]),
            AllowedOAuthFlowsUserPoolClient=True,
            AllowedOAuthScopes=resp.get("AllowedOAuthScopes", MCP_SCOPES),
            CallbackURLs=urls,
            LogoutURLs=urls,
            SupportedIdentityProviders=resp.get("SupportedIdentityProviders", ["COGNITO"]),
        )
    except Exception:
        pass  # Best-effort — don't block the authorize redirect


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
