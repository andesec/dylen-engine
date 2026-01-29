#!/bin/bash
set -euo pipefail
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.debug.yml}"
SERVICE="${SERVICE:-app}"
DEBUG_PORT="${DEBUG_PORT:-5678}"
echo "Waiting for debugger on ${SERVICE}:${DEBUG_PORT}..."
# Find the running container ID for the engine service so we can check its listener state without opening a client connection.
container_id=""
while [ -z "${container_id}" ]; do
  container_id="$(docker compose -f "${COMPOSE_FILE}" ps -q "${SERVICE}" 2>/dev/null || true)"
  if [ -z "${container_id}" ]; then
    sleep 0.5
  fi
done
echo "Found container ID: ${container_id}"

# Poll for a LISTEN socket in /proc/net/tcp{,6} to avoid a probe connection that can race with VS Code attach and cause a disconnect.
while ! docker exec -e DEBUG_PORT="${DEBUG_PORT}" "${container_id}" python - <<'PY'
import os
import sys

target_port = int(os.environ.get("DEBUG_PORT", "5678"))
target_hex = f"{target_port:04X}".upper()

def is_listening(path: str) -> bool:
  try:
    with open(path, "r", encoding="utf-8") as handle:
      lines = handle.read().splitlines()
  except OSError:
    return False
  for line in lines[1:]:
    parts = line.split()
    if len(parts) < 4:
      continue
    local_address = parts[1]
    state = parts[3]
    if state != "0A":
      continue
    try:
      port_hex = local_address.split(":")[1].upper()
    except IndexError:
      continue
    if port_hex == target_hex:
      return True
  return False

if is_listening("/proc/net/tcp") or is_listening("/proc/net/tcp6"):
  sys.exit(0)
sys.exit(1)
PY
do
  sleep 0.5
done
echo "Debugger port 5678 is open inside the container."
echo "Waiting 2 seconds for Docker port forwarding to stabilize..."
sleep 2
echo "Debugger port is ready!"
