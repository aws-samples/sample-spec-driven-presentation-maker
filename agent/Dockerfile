FROM public.ecr.aws/docker/library/python:3.13-slim-bookworm

RUN pip install --no-cache-dir uv

WORKDIR /app

ENV UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1

COPY requirements.txt .
RUN uv pip install --no-cache -r requirements.txt

RUN useradd -m -u 1000 bedrock_agentcore
USER bedrock_agentcore

COPY basic_agent.py agent_factory.py composer.py mcp_clients.py session.py streaming.py ./
COPY prompts/ prompts/
COPY tools/ tools/

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/ping', timeout=2)" || exit 1

CMD ["opentelemetry-instrument", "python", "-m", "basic_agent"]
