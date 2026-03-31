# PNG Worker — Fedora 41 + LibreOffice headless (ARM64 Graviton)
# Converts PPTX → PDF → per-page PNG via SQS polling

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

COPY requirements.txt /app/requirements.txt
RUN python3.13 -m pip install --no-cache-dir -r /app/requirements.txt

COPY main.py /app/main.py
COPY handlers/ /app/handlers/
WORKDIR /app

RUN echo "worker:x:1000:1000::/home/worker:/bin/bash" >> /etc/passwd && \
    mkdir -p /home/worker && chown 1000:1000 /home/worker
USER worker

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python3.13 -c "import os; os._exit(0)" || exit 1

CMD ["python3.13", "main.py"]
