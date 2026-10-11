# Build explicitly: docker build -t game-forge-validator:local validator
# Never built/launched automatically by application startup.
FROM mcr.microsoft.com/playwright:v1.58.2-noble
WORKDIR /validator
RUN npm init -y && npm install --save-exact playwright@1.58.2 && useradd --uid 10001 --create-home forgecheck
COPY runtime.mjs /validator/runtime.mjs
COPY release_runtime.mjs /validator/release_runtime.mjs
COPY audio_probe.mjs /validator/audio_probe.mjs
COPY scenario_runner.mjs /validator/scenario_runner.mjs
COPY audio_activation.mjs /validator/audio_activation.mjs
COPY storage_probe.mjs /validator/storage_probe.mjs
COPY bridge_adapter.mjs /validator/bridge_adapter.mjs
COPY lifecycle_probe.mjs /validator/lifecycle_probe.mjs
COPY surface_probe.mjs /validator/surface_probe.mjs
COPY pixel_probe.mjs /validator/pixel_probe.mjs
USER 10001:10001
ENV HOME=/tmp
CMD ["node", "/validator/runtime.mjs"]
