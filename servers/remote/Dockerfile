# AgentCore Runtime MCP Server container
# Platform: ARM64 (required by AgentCore Runtime)
# Listens on 0.0.0.0:8000/mcp (stateless streamable-http)
# Includes LibreOffice + poppler for synchronous PNG/SVG generation
# cache-bust: 20260413-1457

FROM --platform=linux/arm64 public.ecr.aws/docker/library/fedora:41

RUN dnf install -y --setopt=install_weak_deps=False \
    libreoffice-impress \
    poppler-utils \
    python3.13 \
    python3.13-pip \
    google-noto-sans-fonts \
    google-noto-sans-cjk-jp-fonts \
    && dnf clean all \
    && rm -rf /var/cache/dnf

WORKDIR /app

# uv only exports the locked versions; pip installs them. Pinned by version and digest.
COPY --from=ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 /uv /usr/local/bin/uv

# Dependencies come only from the workspace lock (uv.lock at the repo root): the image
# never resolves. uv needs every member's pyproject.toml to read the workspace.
# --require-hashes + --no-deps: exactly the locked files, nothing pulled in on the side.
COPY pyproject.toml uv.lock /tmp/workspace/
COPY sdpm/pyproject.toml /tmp/workspace/sdpm/pyproject.toml
COPY servers/local/pyproject.toml /tmp/workspace/servers/local/pyproject.toml
COPY servers/remote/pyproject.toml /tmp/workspace/servers/remote/pyproject.toml
COPY agent/pyproject.toml /tmp/workspace/agent/pyproject.toml
COPY api/pyproject.toml /tmp/workspace/api/pyproject.toml
RUN uv export --frozen --directory /tmp/workspace --package sdpm-mcp-server --no-dev --no-emit-workspace \
        -o /tmp/requirements.txt \
    && python3.13 -m pip install --no-cache-dir --require-hashes --no-deps -r /tmp/requirements.txt \
    && rm -rf /tmp/workspace /tmp/requirements.txt

# Skill (engine): imported from source via PYTHONPATH below, like the API Lambda bundle.
# Not pip-installed, so the build fetches nothing outside the lock (no build backend).
COPY sdpm/sdpm/ sdpm/sdpm/

# Bundled knowledge data (references / templates) — served by the shared tool
# contract via SDPM_SKILL_ROOT. Assets stay on S3 (user-extensible, 36MB).
# vendor/ holds reveal.js, ECharts and D3, inlined into HTML decks (sdpm.engine.html):
# reveal.js into every deck, ECharts / D3 into the decks whose slides declare them.
COPY sdpm/references/ sdpm/references/
COPY sdpm/templates/ sdpm/templates/
COPY sdpm/vendor/ sdpm/vendor/
ENV SDPM_SKILL_ROOT=/app/sdpm

# Remote server code. Not installed as a package: it runs from the file with
# PYTHONPATH=/app (shared/), and its directory on sys.path (tools/, storage/).
COPY shared/ shared/
COPY servers/remote/tools/ servers/remote/tools/
COPY servers/remote/storage/ servers/remote/storage/
COPY servers/remote/server.py servers/remote/server.py
COPY servers/remote/server_utils.py servers/remote/server_utils.py
COPY servers/remote/boto_config.py servers/remote/boto_config.py

# /app: shared/. /app/sdpm: the sdpm package (a regular package, so it wins over the
# /app/sdpm namespace directory).
ENV PYTHONPATH=/app:/app/sdpm

RUN echo "mcp:x:1000:1000::/home/mcp:/bin/bash" >> /etc/passwd && \
    mkdir -p /home/mcp && chown 1000:1000 /home/mcp
USER mcp

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python3.13 -c "import socket; s=socket.create_connection(('localhost',8000),2); s.close()" || exit 1

CMD ["opentelemetry-instrument", "python3.13", "servers/remote/server.py"]
