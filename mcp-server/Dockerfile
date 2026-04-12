# AgentCore Runtime MCP Server container
# Platform: ARM64 (required by AgentCore Runtime)
# Listens on 0.0.0.0:8000/mcp (stateless streamable-http)
# Includes LibreOffice + poppler for synchronous PNG/SVG generation

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

# Install skill (engine) first for layer caching
COPY skill/pyproject.toml skill/pyproject.toml
COPY skill/sdpm/ skill/sdpm/
RUN python3.13 -m pip install --no-cache-dir ./skill

# Install mcp-server
COPY shared/ shared/
COPY mcp-server/pyproject.toml mcp-server/pyproject.toml
COPY mcp-server/tools/ mcp-server/tools/
COPY mcp-server/storage/ mcp-server/storage/
COPY mcp-server/server.py mcp-server/server.py
COPY mcp-server/server_utils.py mcp-server/server_utils.py
RUN python3.13 -m pip install --no-cache-dir ./mcp-server

ENV PYTHONPATH=/app

RUN echo "mcp:x:1000:1000::/home/mcp:/bin/bash" >> /etc/passwd && \
    mkdir -p /home/mcp && chown 1000:1000 /home/mcp
USER mcp

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python3.13 -c "import socket; s=socket.create_connection(('localhost',8000),2); s.close()" || exit 1

CMD ["opentelemetry-instrument", "python3.13", "mcp-server/server.py"]
