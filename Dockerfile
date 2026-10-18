FROM node:22-bookworm-slim AS frontend
WORKDIR /web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock \
    && useradd --uid 10001 --create-home forge \
    && mkdir -p /app/.data /run/validator && chown -R forge:forge /app/.data /run/validator
COPY manage.py ./
COPY gameforge/ gameforge/
COPY studio/ studio/
COPY generation/ generation/
COPY validation/ validation/
COPY --from=frontend /web/dist/ web/dist/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
CMD ["gunicorn", "gameforge.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--timeout", "0"]
