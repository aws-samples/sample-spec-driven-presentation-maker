# AgentCore Runtime Agent container. Build context: the repository root
# (infra/lib/agent-stack.ts), because the dependencies come from the workspace lock.
FROM public.ecr.aws/docker/library/python:3.13-slim-bookworm

# Pinned by version and digest.
COPY --from=ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 /uv /usr/local/bin/uv

WORKDIR /app

ENV UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1

# Dependencies come only from the workspace lock (uv.lock at the repo root): the image
# never resolves. uv needs every member's pyproject.toml to read the workspace.
# --require-hashes + --no-deps: exactly the locked files, nothing pulled in on the side.
COPY pyproject.toml uv.lock /tmp/workspace/
COPY sdpm/pyproject.toml /tmp/workspace/sdpm/pyproject.toml
COPY servers/local/pyproject.toml /tmp/workspace/servers/local/pyproject.toml
COPY servers/remote/pyproject.toml /tmp/workspace/servers/remote/pyproject.toml
COPY agent/pyproject.toml /tmp/workspace/agent/pyproject.toml
COPY api/pyproject.toml /tmp/workspace/api/pyproject.toml
RUN uv export --frozen --directory /tmp/workspace --package sdpm-agent --no-dev --no-emit-workspace \
        -o /tmp/requirements.txt \
    && uv pip install --no-cache --require-hashes --no-deps -r /tmp/requirements.txt \
    && rm -rf /tmp/workspace /tmp/requirements.txt

RUN useradd -m -u 1000 bedrock_agentcore
USER bedrock_agentcore

COPY agent/background.py agent/basic_agent.py agent/compose_messaging.py agent/cost_logger.py agent/errors.py agent/event_ring.py agent/factory.py agent/composition.py agent/mcp_clients.py agent/message_hooks.py agent/model_profiles.py agent/resilience.py agent/session.py agent/session_guard.py agent/session_handle.py agent/session_runtime.py agent/steer_inbox.py agent/stop_guard.py agent/streaming.py agent/token_holder.py agent/ws_entry.py ./
COPY shared/__init__.py shared/session_owner.py shared/snapshot_random.py shared/
COPY agent/prompts/ prompts/
COPY agent/modes/ modes/
COPY agent/tools/ tools/

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/ping', timeout=2)" || exit 1

CMD ["opentelemetry-instrument", "python", "-m", "basic_agent"]
