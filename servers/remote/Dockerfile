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

# constraints.txt pins the full dependency tree for reproducible image builds
# (see the mcp 2.0 breakage). Regenerate with `make lock` after editing pyproject.toml.
COPY servers/remote/constraints.txt servers/remote/constraints.txt

# Install skill (engine) first for layer caching
COPY sdpm/pyproject.toml sdpm/pyproject.toml
COPY sdpm/sdpm/ sdpm/sdpm/
RUN python3.13 -m pip install --no-cache-dir -c servers/remote/constraints.txt ./sdpm

# Bundled knowledge data (references / templates) — served by the shared tool
# contract via SDPM_SKILL_ROOT. Assets stay on S3 (user-extensible, 36MB).
COPY sdpm/references/ sdpm/references/
COPY personas/ personas/
COPY sdpm/templates/ sdpm/templates/
ENV SDPM_SKILL_ROOT=/app/sdpm

# Install remote server
COPY shared/ shared/
COPY servers/remote/pyproject.toml servers/remote/pyproject.toml
COPY servers/remote/tools/ servers/remote/tools/
COPY servers/remote/storage/ servers/remote/storage/
COPY servers/remote/server.py servers/remote/server.py
COPY servers/remote/server_utils.py servers/remote/server_utils.py
RUN python3.13 -m pip install --no-cache-dir -c servers/remote/constraints.txt ./servers/remote

ENV PYTHONPATH=/app

RUN echo "mcp:x:1000:1000::/home/mcp:/bin/bash" >> /etc/passwd && \
    mkdir -p /home/mcp && chown 1000:1000 /home/mcp
USER mcp

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python3.13 -c "import socket; s=socket.create_connection(('localhost',8000),2); s.close()" || exit 1

CMD ["opentelemetry-instrument", "python3.13", "servers/remote/server.py"]
