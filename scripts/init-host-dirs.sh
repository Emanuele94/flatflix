#!/usr/bin/env bash
# Create the host folders compose bind-mounts, owned by PUID:PGID, before the
# first `docker compose up` (Docker would otherwise create them as root).
# Idempotent. Reads only four keys from the local env file; never sources it.
set -euo pipefail

cd "$(dirname "$0")/.."
ENV_FILE=".env"

get() {
  local key=$1 default=$2 value=""
  if [ -f "$ENV_FILE" ]; then
    value=$(grep -E "^${key}=" "$ENV_FILE" | tail -n 1 | sed -E "s/^${key}=//" || true)
  fi
  printf '%s' "${value:-$default}"
}

MEDIA_ROOT=$(get MEDIA_ROOT ./data/media)
INCOMPLETE_DIR=$(get INCOMPLETE_DIR ./data/incomplete)
PUID=$(get PUID 1000)
PGID=$(get PGID 1000)

dirs=(
  "$MEDIA_ROOT/Film"
  "$MEDIA_ROOT/SerieTV"
  "$INCOMPLETE_DIR"
  "qbittorrent/config"
)

SUDO=""
if [ "$(id -u)" != "$PUID" ] && [ "$(id -u)" != "0" ]; then
  SUDO="sudo"
fi

for d in "${dirs[@]}"; do
  mkdir -p "$d" 2>/dev/null || $SUDO mkdir -p "$d"
  owner=$(stat -c '%u:%g' "$d")
  if [ "$owner" != "$PUID:$PGID" ]; then
    $SUDO chown "$PUID:$PGID" "$d"
  fi
  $SUDO chmod 0775 "$d"
  printf '%s %s\n' "$d" "$(stat -c '%u:%g' "$d")"
done
