# Chasing Tail(s) — LAN-only fishing trip planner (FastAPI + SQLite)
# Non-root, single container, port 8000. Contract: see ../docker-compose repo
# (likelyabot/docker-compose, folder fishing/) — healthcheck hits /healthz.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Non-root user (compose mounts a named volume at /app/data; the dir is
# created here so the volume inherits fisher's ownership).
RUN groupadd -g 10001 fisher \
    && useradd -u 10001 -g fisher -m -d /home/fisher fisher \
    && mkdir -p /app/data \
    && chown -R fisher:fisher /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app

USER fisher
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=5)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
