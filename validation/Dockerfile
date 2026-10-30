FROM python:3.12-slim-bookworm
# Standard system packages; no source or runtime from the previous generator is copied.
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm chromium ca-certificates \
    && rm -rf /var/lib/apt/lists/* && useradd --uid 10001 --create-home forgecheck
RUN pip install --no-cache-dir playwright==1.58.0
RUN mkdir -p /run/validator && chown 10001:10001 /run/validator
WORKDIR /opt/validator
COPY validation/ /opt/validator/validation/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp CHROMIUM_EXECUTABLE=/usr/bin/chromium
USER 10001:10001
CMD ["sleep", "infinity"]
