# /// script
# requires-python = ">=3.10"
# dependencies = ["websockets>=13", "boto3>=1.34"]
# ///
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Reference client for the programmatic client of an SDPM Cloud deployment.

Creates decks as the signed-in user from a script, cron job, Lambda function or
Step Functions state machine. One browser sign-in (``login``) stores a refresh
token; ``run`` and ``status`` then work unattended until it expires.

  uv run sdpm_client.py login --site https://xxxx.cloudfront.net --client-id <id>
  uv run sdpm_client.py run "Make a 3-slide deck about ..."
  uv run sdpm_client.py status <session id>   # running, then done (or needs_input, failed, cancelled)

Settings: ``--site`` / ``SDPM_SITE`` (the Web UI URL), ``--client-id`` /
``SDPM_CLIENT_ID`` (the ProgrammaticClientId output of SdpmAuth) and ``--store`` /
``SDPM_TOKEN_STORE`` (``file:<path>``, default under ~/.config, or
``secretsmanager:<name or ARN>``). ``login`` remembers them in
~/.config/sdpm-programmatic-client/config.json (no secrets in that file).

Every command prints one JSON object on stdout. Exit codes: 0 success (whatever the
state), 1 error, 2 usage, 3 the refresh token is expired, revoked or invalid (run
``login`` again).

The functions ``start_job`` and ``job_status`` are the same steps for code that
imports this file (for example a Lambda handler); see docs/en/programmatic-access.md.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# The programmatic client's only callback URL (auth.programmaticClient in infra/config.yaml).
CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 8765
REDIRECT_URI = f"http://{CALLBACK_HOST}:{CALLBACK_PORT}"
SCOPE = "openid profile email sdpm-mcp/invoke"
SUBPROTOCOL = "base64UrlBearerAuthorization"
LOGIN_TIMEOUT_S = 300
ACCEPT_TIMEOUT_S = 120
WS_TIMEOUT_S = 120  # opening /ws and the resume answers (a reclaimed session starts a microVM)
LATEST_SEQ = 2**53 - 1  # a resume from_seq past any head
LOOKBACK = 8  # events read back from an ended period's head, to find its ``work idle``
POLL_INTERVAL_S = 60  # status polls no more often than this
FINAL_STATES = ("done", "needs_input", "failed", "cancelled")

EXIT_ERROR = 1
EXIT_TOKEN = 3


class ClientError(Exception):
    """A step failed; the message says which and why (never a token)."""


class RefreshTokenExpired(ClientError):
    """The refresh token was refused (expired, revoked or invalid): sign in again."""


# --- settings ---------------------------------------------------------------------


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "sdpm-programmatic-client"


@dataclass
class Settings:
    site: str
    client_id: str
    store: str

    @classmethod
    def resolve(cls, site: str | None = None, client_id: str | None = None, store: str | None = None) -> "Settings":
        """Arguments first, then SDPM_SITE / SDPM_CLIENT_ID / SDPM_TOKEN_STORE, then config.json."""
        saved: dict = {}
        try:
            saved = json.loads((config_dir() / "config.json").read_text())
        except (OSError, ValueError, RuntimeError):
            pass
        site = site or os.environ.get("SDPM_SITE") or saved.get("site")
        client_id = client_id or os.environ.get("SDPM_CLIENT_ID") or saved.get("client_id")
        store = store or os.environ.get("SDPM_TOKEN_STORE") or saved.get("store") or f"file:{config_dir() / 'token.json'}"
        if not site or not client_id:
            raise ClientError("set --site and --client-id (or SDPM_SITE and SDPM_CLIENT_ID)")
        return cls(site.rstrip("/"), client_id, store)

    def remember(self) -> None:
        path = config_dir() / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(json.dumps({"site": self.site, "client_id": self.client_id, "store": self.store}, indent=2))


@dataclass
class Deployment:
    """What the deployment publishes: aws-exports.json and the user pool's OIDC metadata."""

    client_id: str
    region: str
    agent_runtime_arn: str
    api_base_url: str
    authorization_endpoint: str
    token_endpoint: str


def discover(settings: Settings) -> Deployment:
    exports = http_json(f"{settings.site}/aws-exports.json")
    oidc = http_json(f"{exports['authority'].rstrip('/')}/.well-known/openid-configuration")
    return Deployment(
        client_id=settings.client_id,
        region=exports["awsRegion"],
        agent_runtime_arn=exports["agentRuntimeArn"],
        api_base_url=exports["apiBaseUrl"].rstrip("/"),
        authorization_endpoint=oidc["authorization_endpoint"],
        token_endpoint=oidc["token_endpoint"],
    )


# --- HTTP -------------------------------------------------------------------------


def http_json(url: str, form: dict | None = None, token: str | None = None) -> dict:
    if not url.startswith("https://"):
        raise ClientError(f"refusing a non-HTTPS URL: {url}")
    headers = {"Accept": "application/json"}
    body = None
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as resp:  # noqa: S310 - HTTPS checked above
        return json.loads(resp.read())


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def claims(jwt: str) -> dict:
    """The payload of a token Cognito just issued to us (not a verification)."""
    part = jwt.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def token_request(deployment: Deployment, form: dict) -> dict:
    try:
        return http_json(deployment.token_endpoint, {"client_id": deployment.client_id, **form})
    except urllib.error.HTTPError as e:
        try:
            error = json.loads(e.read()).get("error", "")
        except ValueError:
            error = ""
        if form.get("grant_type") == "refresh_token" and error in ("invalid_grant", "invalid_client"):
            raise RefreshTokenExpired("the refresh token is expired, revoked or invalid: run login again") from None
        raise ClientError(f"token endpoint refused the request ({e.code} {error or e.reason})") from None


# --- token store ------------------------------------------------------------------


def _secretsmanager(name: str, deployment: Deployment | None):
    import boto3

    region = None
    if name.startswith("arn:"):
        region = name.split(":")[3]
    elif boto3.session.Session().region_name is None and deployment is not None:
        region = deployment.region
    return boto3.client("secretsmanager", region_name=region)


def load_refresh_token(store: str, deployment: Deployment | None = None) -> str:
    kind, _, where = store.partition(":")
    try:
        if kind == "file":
            text = Path(where).expanduser().read_text()
        elif kind == "secretsmanager":
            text = _secretsmanager(where, deployment).get_secret_value(SecretId=where)["SecretString"]
        else:
            raise ClientError(f"unknown token store {kind!r}: use file:<path> or secretsmanager:<name>")
    except FileNotFoundError:
        raise ClientError(f"no refresh token in {store}: run login first") from None
    return json.loads(text)["refresh_token"]


def save_refresh_token(store: str, refresh_token: str, deployment: Deployment) -> None:
    """Store the token: a 0600 file, or a Secrets Manager secret (nothing on disk then)."""
    value = json.dumps({"refresh_token": refresh_token, "client_id": deployment.client_id,
                        "obtained_at": int(time.time())})
    kind, _, where = store.partition(":")
    if kind == "file":
        path = Path(where).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(value)
        path.chmod(0o600)
    elif kind == "secretsmanager":
        client = _secretsmanager(where, deployment)
        try:
            client.put_secret_value(SecretId=where, SecretString=value)
        except client.exceptions.ResourceNotFoundException:
            client.create_secret(Name=where, SecretString=value,
                                 Description="SDPM programmatic client refresh token")
    else:
        raise ClientError(f"unknown token store {kind!r}: use file:<path> or secretsmanager:<name>")


# --- login ------------------------------------------------------------------------


def login(settings: Settings, open_browser: bool = True, timeout_s: int = LOGIN_TIMEOUT_S) -> dict:
    """One browser sign-in (code flow + PKCE) through a loopback listener on 127.0.0.1:8765."""
    deployment = discover(settings)
    verifier = b64url(secrets.token_bytes(32))
    state = b64url(secrets.token_bytes(16))
    url = deployment.authorization_endpoint + "?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": deployment.client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "state": state,
        "code_challenge": b64url(hashlib.sha256(verifier.encode()).digest()),
        "code_challenge_method": "S256",
    })
    params = _wait_for_redirect(url, open_browser, timeout_s)
    if params.get("state") != state:
        raise ClientError("the redirect carried another sign-in's state: run login again")
    if "error" in params:
        raise ClientError(f"sign-in failed: {params['error']}")
    tokens = token_request(deployment, {
        "grant_type": "authorization_code",
        "code": params["code"],
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
    })
    save_refresh_token(settings.store, tokens["refresh_token"], deployment)
    settings.remember()
    access = claims(tokens["access_token"])
    return {"signedIn": True, "sub": access["sub"], "scope": access.get("scope"), "store": settings.store}


def _wait_for_redirect(url: str, open_browser: bool, timeout_s: int) -> dict:
    got: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server API
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            if "code" not in query and "error" not in query:
                self.send_error(404)
                return
            got.update(query)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Sign-in received. You can close this tab.\n")

        def log_message(self, *args):  # keep the code out of the terminal
            pass

    try:
        server = HTTPServer((CALLBACK_HOST, CALLBACK_PORT), Handler)  # loopback only
    except OSError as e:
        raise ClientError(f"cannot listen on {REDIRECT_URI}: {e.strerror}") from None
    print(f"Sign in here (waiting up to {timeout_s // 60} min):\n{url}", file=sys.stderr, flush=True)
    if open_browser:
        webbrowser.open(url)
    server.timeout = 1
    deadline = time.monotonic() + timeout_s
    try:
        while not got and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if not got:
        raise ClientError("no sign-in redirect arrived in time")
    return got


# --- jobs -------------------------------------------------------------------------


def owner_prefix(sub: str) -> str:
    """The session id prefix the agent admits for ``sub`` (shared/session_owner.py)."""
    return hashlib.sha256(sub.encode("utf-8")).hexdigest()[:16]


def new_session_id(sub: str) -> str:
    return f"{owner_prefix(sub)}-{uuid.uuid4()}"


def fresh_tokens(settings: Settings, deployment: Deployment) -> dict:
    refresh_token = load_refresh_token(settings.store, deployment)
    return token_request(deployment, {"grant_type": "refresh_token", "refresh_token": refresh_token})


def _connect(deployment: Deployment, access_token: str, session_id: str):
    """The session's Agent ``/ws`` (connecting to a reclaimed session starts a microVM)."""
    import websockets

    arn = urllib.parse.quote(deployment.agent_runtime_arn, safe="")
    url = (f"wss://bedrock-agentcore.{deployment.region}.amazonaws.com/runtimes/{arn}/ws"
           f"?qualifier=DEFAULT&X-Amzn-Bedrock-AgentCore-Runtime-Session-Id={session_id}")
    protocols = [f"{SUBPROTOCOL}.{b64url(access_token.encode())}", SUBPROTOCOL]
    return websockets.connect(url, subprotocols=protocols, max_size=None, open_timeout=WS_TIMEOUT_S,
                              ping_interval=None)


def frame_messages(frame: dict, chunks: dict) -> list[dict]:
    """The messages of one server frame: a control message or event item as is, the items of
    a ``batch``, or the item a ``chunk`` completes (``chunks`` keeps the parts in between)."""
    if "batch" in frame:
        return list(frame["batch"])
    if "chunk" in frame:
        parts = chunks.setdefault(frame["chunk"], {})
        parts[frame["i"]] = frame["data"]
        if len(parts) < frame["n"]:
            return []
        del chunks[frame["chunk"]]
        return [json.loads("".join(parts[i] for i in range(frame["n"])))]
    return [frame]


async def _messages(ws, deadline: float, what: str):
    """Control messages and event items from the agent until ``deadline``; raises on ``error``."""
    import websockets

    chunks: dict = {}
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ClientError(f"the agent did not answer {what} in time")
        try:
            frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
        except asyncio.TimeoutError:
            continue
        except websockets.ConnectionClosed as e:
            raise ClientError(f"the connection closed before {what} was answered ({e.rcvd.code if e.rcvd else 'no code'})") from None
        for message in frame_messages(frame, chunks) if isinstance(frame, dict) else []:
            if message.get("ctl") == "error":
                raise ClientError(f"the agent refused {what}: {message.get('code')} {message.get('error')}")
            yield message


async def _ack(ws, deadline: float, what: str, ctl: str) -> dict:
    async for message in _messages(ws, deadline, what):
        if message.get("ctl") == ctl:
            return message
    raise ClientError(f"the connection closed before {what} was answered")


async def _submit(deployment: Deployment, access_token: str, session_id: str, prompt: str) -> dict:
    """Send the prompt on /ws and leave at ``accepted``; the session keeps working."""
    async with _connect(deployment, access_token, session_id) as ws:
        # The client speaks first; the agent sends nothing before it.
        await ws.send(json.dumps({"type": "prompt", "id": uuid.uuid4().hex[:16], "prompt": prompt, "mode": "vibe"}))
        return await _ack(ws, time.monotonic() + ACCEPT_TIMEOUT_S, "the prompt", "accepted")


async def _work_period(deployment: Deployment, access_token: str, session_id: str) -> dict:
    """Where the session's work period stands, from ``resume`` on /ws (leaves at once).

    Returns ``working`` (``resumeAck.working``), ``how`` (the ``work idle`` event's, when the
    period has ended and the session still has it) and ``reclaimed`` (the session is not in
    the agent's process any more: nothing of it is running).
    """
    async with _connect(deployment, access_token, session_id) as ws:
        deadline = time.monotonic() + WS_TIMEOUT_S
        # A from_seq past the head replays nothing: the ack alone says where the session is.
        await ws.send(json.dumps({"type": "resume", "from_seq": LATEST_SEQ}))
        ack = await _ack(ws, deadline, "resume", "resumeAck")
        if ack.get("working"):
            return {"working": True, "how": None, "reclaimed": False}
        head = ack.get("head") or 0
        if head == 0:
            # The agent's answer for a session it does not hold (reclaimed, or never started).
            return {"working": False, "how": None, "reclaimed": True}
        # The period has ended: ``work idle`` is its last event. Read the last few.
        await ws.send(json.dumps({"type": "resume", "from_seq": max(0, head - LOOKBACK)}))
        ack = await _ack(ws, deadline, "resume", "resumeAck")
        if ack.get("working"):
            return {"working": True, "how": None, "reclaimed": False}  # a new period started
        how = None
        head = ack.get("head") or 0
        if ack.get("replay_from", head + 1) <= head:
            async for message in _messages(ws, deadline, "resume"):
                seq = message.get("seq")
                if not isinstance(seq, int):
                    continue
                work = (message.get("ev") or {}).get("work") if isinstance(message.get("ev"), dict) else None
                if isinstance(work, dict):
                    how = work.get("how") if work.get("state") == "idle" else None
                if seq >= head:
                    break
        return {"working": False, "how": how, "reclaimed": False}


def job_state(period: dict, has_pptx: bool) -> str:
    """The job's state from its work period and whether its deck has a PPTX.

    ``running`` while the session works; once its work period has ended: ``done`` (ended
    ``finished`` with a PPTX), ``needs_input`` (``finished`` without one: most likely a
    question), ``cancelled``, or ``failed`` (``error``, ``watchdog``, ``sigterm``). A
    reclaimed session has nobody working on it: ``done`` with a PPTX, else ``needs_input``.
    An ended period whose ``work idle`` the replay does not hold stays ``running`` (never
    ``done``): the agent always ends a period with that event, and it was there in every
    measurement on dev, so the caller's own timeout ends the wait if it ever is missing.
    """
    if period.get("working"):
        return "running"
    if period.get("reclaimed"):
        return "done" if has_pptx else "needs_input"
    how = period.get("how")
    if how is None:
        return "running"
    if how == "finished":
        return "done" if has_pptx else "needs_input"
    if how == "cancelled":
        return "cancelled"
    return "failed"


def start_job(settings: Settings, prompt: str) -> dict:
    """Start one deck: a new owner-prefixed session, the prompt in mode vibe, leave at accepted."""
    deployment = discover(settings)
    tokens = fresh_tokens(settings, deployment)
    session_id = new_session_id(claims(tokens["access_token"])["sub"])
    accepted = asyncio.run(_submit(deployment, tokens["access_token"], session_id, prompt))
    return {"sessionId": session_id, "accepted": accepted.get("as")}


def job_status(settings: Settings, session_id: str) -> dict:
    """The job's state (see ``job_state``) and its deck: poll no more often than every
    POLL_INTERVAL_S, and stop at a state in FINAL_STATES."""
    deployment = discover(settings)
    tokens = fresh_tokens(settings, deployment)
    # The work period first: once it has ended, the deck read after it is the final one.
    period = asyncio.run(_work_period(deployment, tokens["access_token"], session_id))
    id_token = tokens["id_token"]
    listing = http_json(f"{deployment.api_base_url}/decks", token=id_token)
    deck = next((d for d in listing.get("decks", []) if d.get("chatSessionId") == session_id), None)
    detail = {}
    if deck is not None:
        detail = http_json(f"{deployment.api_base_url}/decks/{urllib.parse.quote(deck['deckId'])}", token=id_token)
    pptx_url = detail.get("pptxUrl")
    return {
        "sessionId": session_id,
        "state": job_state(period, bool(pptx_url)),
        "working": period["working"],
        "how": period["how"],
        "reclaimed": period["reclaimed"],
        "deckId": deck["deckId"] if deck else None,
        "name": detail.get("name"),
        "slideCount": detail.get("slideCount", 0),
        "hasPptx": bool(pptx_url),
        "pptxUrl": pptx_url,
    }


# --- CLI --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--site", help="Web UI URL (SDPM_SITE)")
    common.add_argument("--client-id", help="programmatic client ID (SDPM_CLIENT_ID)")
    common.add_argument("--store", help="file:<path> or secretsmanager:<name> (SDPM_TOKEN_STORE)")
    parser = argparse.ArgumentParser(description="Create SDPM decks as yourself from automation.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_login = sub.add_parser("login", parents=[common], help="sign in once in a browser and store a refresh token")
    p_login.add_argument("--no-browser", action="store_true", help="print the sign-in URL without opening it")
    p_login.add_argument("--timeout", type=int, default=LOGIN_TIMEOUT_S, help="seconds to wait for the sign-in")
    p_run = sub.add_parser("run", parents=[common], help="start a deck from a prompt; prints its session id")
    p_run.add_argument("prompt", help="the request ('-' reads it from stdin)")
    p_status = sub.add_parser("status", parents=[common], help="report whether a session's work has ended, and its deck")
    p_status.add_argument("session_id")
    args = parser.parse_args(argv)

    try:
        settings = Settings.resolve(args.site, args.client_id, args.store)
        if args.command == "login":
            result = login(settings, open_browser=not args.no_browser, timeout_s=args.timeout)
        elif args.command == "run":
            prompt = sys.stdin.read() if args.prompt == "-" else args.prompt
            if not prompt.strip():
                raise ClientError("the prompt is empty")
            result = start_job(settings, prompt)
        else:
            result = job_status(settings, args.session_id)
    except RefreshTokenExpired as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_TOKEN
    except (ClientError, urllib.error.URLError, OSError, KeyError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_ERROR
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
