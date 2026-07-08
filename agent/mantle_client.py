"""Bedrock Mantle client adapter — SigV4-signed httpx for OpenAI-compatible API.

Note: _MantleOpenAIModel overrides _get_client (internal to strands-agents OpenAIModel).
Tested with strands-agents>=1.30.0. If the SDK restructures OpenAIModel internals,
this module may need updating.
"""

import contextlib

import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.session import Session as BotocoreSession


class _SigV4Transport(httpx.AsyncBaseTransport):
    """httpx transport that signs every request with SigV4 before sending."""

    def __init__(self, region: str, service: str = "bedrock"):
        self._region = region
        self._service = service
        self._transport = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        creds = BotocoreSession().get_credentials().get_frozen_credentials()
        body = request.content if request.content else b""
        aws_req = AWSRequest(
            method=request.method,
            url=str(request.url),
            headers={k: v for k, v in request.headers.items()},
            data=body,
        )
        SigV4Auth(creds, self._service, self._region).add_auth(aws_req)
        for key, val in aws_req.headers.items():
            request.headers[key] = val
        return await self._transport.handle_async_request(request)

    async def aclose(self):
        await self._transport.aclose()


def mantle_model(model_id: str, region: str = "us-east-1"):
    """Create a Strands OpenAIModel pointing at bedrock-mantle with SigV4 auth.

    Usage:
        from mantle_client import mantle_model
        model = mantle_model("openai.gpt-5.4", region="us-east-1")
    """
    from strands.models.openai import OpenAIModel

    class _MantleOpenAIModel(OpenAIModel):
        """OpenAIModel subclass that creates a fresh http_client per request.

        Also patches tool call IDs to be globally unique (mantle returns
        sequential 'call_0', 'call_1' that reset each turn).
        """

        def __init__(self, region: str, **kwargs):
            self._mantle_region = region
            self._call_counter = 0
            super().__init__(**kwargs)

        def format_chunk(self, event: dict, **kwargs) -> dict:
            chunk = super().format_chunk(event, **kwargs)
            # Patch toolUseId in contentBlockStart
            start = chunk.get("contentBlockStart", {}).get("start", {}).get("toolUse")
            if start and "toolUseId" in start:
                self._call_counter += 1
                start["toolUseId"] = f"mantle_{self._call_counter:04d}"
            return chunk

        @contextlib.asynccontextmanager
        async def _get_client(self):
            import openai
            transport = _SigV4Transport(region=self._mantle_region)
            http_client = httpx.AsyncClient(
                transport=transport,
                timeout=httpx.Timeout(120.0, connect=10.0),
            )
            client = openai.AsyncOpenAI(
                base_url=f"https://bedrock-mantle.{self._mantle_region}.api.aws/openai/v1",
                http_client=http_client,
                api_key="unused",
            )
            try:
                yield client
            finally:
                await http_client.aclose()

    return _MantleOpenAIModel(region=region, model_id=model_id)
