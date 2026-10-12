FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS python-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_NO_SYNC=1 \
    HOME=/home/prompt2play \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev \
    && useradd --create-home --uid 10001 prompt2play \
    && mkdir -p /data/artifacts \
    && chown -R prompt2play:prompt2play /app /data /home/prompt2play

COPY alembic.ini ./
COPY alembic ./alembic


FROM python-runtime AS api
USER prompt2play
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=6 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=2)"]
CMD ["uvicorn", "prompt2play.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]


FROM python-runtime AS migration
USER prompt2play
CMD ["alembic", "upgrade", "head"]


FROM python-runtime AS model-worker
USER prompt2play
CMD ["celery", "-A", "prompt2play.tasks:celery_app", "worker", "-Q", "models", "--hostname=models@%h", "--concurrency=4", "--loglevel=INFO"]


FROM python-runtime AS workflow-worker
USER prompt2play
CMD ["celery", "-A", "prompt2play.tasks:celery_app", "worker", "-Q", "workflow", "--hostname=workflow@%h", "--concurrency=1", "--loglevel=INFO"]


FROM python-runtime AS beat
USER prompt2play
CMD ["celery", "-A", "prompt2play.tasks:celery_app", "beat", "--schedule=/tmp/celerybeat-schedule", "--loglevel=INFO"]


FROM python-runtime AS validation-worker
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
USER root
RUN mkdir -p /ms-playwright \
    && playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright
USER prompt2play
CMD ["celery", "-A", "prompt2play.tasks:celery_app", "worker", "-Q", "validation", "--hostname=validation@%h", "--concurrency=2", "--loglevel=INFO"]
