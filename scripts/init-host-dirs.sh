#!/usr/bin/env bash
# Create the host folders compose bind-mounts, owned by PUID:PGID, before the
# first `docker compose up` (Docker would otherwise create them as root), and
# check that KVM_GID matches the group of /dev/kvm (the sandbox microVM needs it).
# Idempotent. Reads only DATA_ROOT, PUID, PGID and KVM_GID from the local env file;
# never sources it and never writes it.
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

DATA_ROOT=$(get DATA_ROOT ./data)
PUID=$(get PUID 1000)
PGID=$(get PGID 1000)
KVM_GID=$(get KVM_GID "")

dirs=(
  "$DATA_ROOT"
  "$DATA_ROOT/media"
  "$DATA_ROOT/media/Film"
  "$DATA_ROOT/media/SerieTV"
  "$DATA_ROOT/quarantine"
  "$DATA_ROOT/quarantine/Film"
  "$DATA_ROOT/quarantine/SerieTV"
  "$DATA_ROOT/incomplete"
  "$DATA_ROOT/rejected"
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
  if [ "$d" = "$DATA_ROOT/rejected" ]; then
    # Suspect files must not be readable by other host users (D-55).
    $SUDO chmod 0700 "$d"
  else
    $SUDO chmod 0775 "$d"
  fi
  printf '%s %s\n' "$d" "$(stat -c '%u:%g' "$d")"
done

if [ ! -e /dev/kvm ]; then
  echo "FAIL /dev/kvm not found: enable CPU virtualization (see docs/setup.md)"
  exit 1
fi
kvm_group=$(stat -c '%g' /dev/kvm)
if [ "$KVM_GID" != "$kvm_group" ]; then
  echo "FAIL KVM_GID in .env is '$KVM_GID', /dev/kvm belongs to group $kvm_group: set KVM_GID=$kvm_group"
  exit 1
fi
echo "OK KVM_GID $kvm_group"
