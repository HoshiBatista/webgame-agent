#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
validator_name=${VALIDATOR_CONTAINER:-gf-mini-validator}
case "$validator_name" in
  gf-mini-validator|gf-mini-validator-tests) ;;
  *) echo "Choose gf-mini-validator or gf-mini-validator-tests" >&2; exit 2 ;;
esac
docker build -f validation/Dockerfile -t gameforge-mini-validator:current .
# Replace only this project's disposable browser container; no persistent game data lives here.
docker rm -f "$validator_name" >/dev/null 2>&1 || true
docker run -d --init --name "$validator_name" --network none --read-only \
  --cap-drop ALL --security-opt no-new-privileges --memory 1g --cpus 2 \
  --pids-limit 256 --shm-size 256m --tmpfs /tmp:rw,nosuid,size=256m \
  gameforge-mini-validator:current
