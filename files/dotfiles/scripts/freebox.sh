#!/bin/bash

set -euo pipefail

mountpoint="${1:-$HOME/mnt/freebox}"
remote=':smb,host=192.168.1.254,user=guest:/Disque dur'

# A dropped FUSE connection leaves a mountpoint which cannot be stat'ed
# ("Transport endpoint is not connected"). Detach it before attempting to use
# the directory again. A live mount is owned by the systemd service below, so
# this only runs after that service has stopped or failed.
if ! test -d "$mountpoint"; then
  fusermount3 -uz "$mountpoint" 2>/dev/null || fusermount -uz "$mountpoint" 2>/dev/null || true
fi

mkdir -p "$mountpoint"

while ! ping -c 1 192.168.1.254 >/dev/null 2>&1; do
  sleep 1
done

if mountpoint -q "$mountpoint"; then
  echo "Already mounted: $mountpoint"
  exit 0
fi

exec rclone mount "$remote" "$mountpoint" \
  --dir-cache-time 10m \
  --vfs-cache-mode full \
  --network-mode
