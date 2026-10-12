FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev
RUN mkdir -p /ms-playwright \
    && uv run playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright

COPY alembic.ini ./
COPY alembic ./alembic

RUN useradd --create-home --uid 10001 prompt2play \
    && mkdir -p /data/artifacts \
    && chown -R prompt2play:prompt2play /app /data
USER prompt2play

ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "prompt2play.main:app", "--host", "0.0.0.0", "--port", "8000"]
