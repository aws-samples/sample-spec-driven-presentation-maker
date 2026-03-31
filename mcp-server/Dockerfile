# AgentCore Runtime MCP Server container
# Platform: ARM64 (required by AgentCore Runtime)
# Listens on 0.0.0.0:8000/mcp (stateless streamable-http)

FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.13-slim

WORKDIR /app

# Install skill (engine) first for layer caching
COPY skill/pyproject.toml skill/pyproject.toml
COPY skill/sdpm/ skill/sdpm/
RUN pip install --no-cache-dir ./skill

# Install mcp-server
COPY shared/ shared/
COPY mcp-server/pyproject.toml mcp-server/pyproject.toml
COPY mcp-server/tools/ mcp-server/tools/
COPY mcp-server/storage/ mcp-server/storage/
COPY mcp-server/server.py mcp-server/server.py
RUN pip install --no-cache-dir ./mcp-server

ENV PYTHONPATH=/app

RUN useradd -m -u 1000 mcp
USER mcp

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import socket; s=socket.create_connection(('localhost',8000),2); s.close()" || exit 1

CMD ["opentelemetry-instrument", "python", "mcp-server/server.py"]
