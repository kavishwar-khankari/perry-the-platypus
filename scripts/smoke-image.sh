#!/usr/bin/env bash
set -euo pipefail

image="${1:-perry:local}"
container="perry-image-smoke-$$"
python3 -u tests/fake_services.py &
fake_pid=$!

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  kill "$fake_pid" >/dev/null 2>&1 || true
  wait "$fake_pid" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run --detach --name "$container" \
  --network host \
  --env PERRY_ZEN_API_KEY=fake-test-key \
  --env PERRY_ZEN_URL=http://127.0.0.1:18081/v1/systemone \
  --env PERRY_APPRISE_URL=http://127.0.0.1:18081/notify/global \
  --env PERRY_APPROVED_EVENT_ID=image-smoke-alert \
  "$image" >/dev/null

PERRY_TEST_BASE=http://127.0.0.1:8000 uv run python tests/image_smoke.py
