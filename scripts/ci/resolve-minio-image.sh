#!/usr/bin/env bash
# Pick a MinIO image that is pullable from the current network (CI mirrors vary).
set -euo pipefail

TAG="${MINIO_TAG:-RELEASE.2024-12-18T13-15-44Z}"

log() {
  echo "$@" >&2
}

if [[ -n "${MINIO_IMAGE:-}" ]]; then
  log "==> MinIO: using MINIO_IMAGE=$MINIO_IMAGE"
  docker pull -q "$MINIO_IMAGE" >&2
  printf '%s\n' "$MINIO_IMAGE"
  exit 0
fi

candidates=(
  "ghcr.io/coollabsio/minio:latest"
  "ghcr.io/coollabsio/minio:${TAG}"
  "quay.io/minio/minio:${TAG}"
  "minio/minio:${TAG}"
)

for img in "${candidates[@]}"; do
  log "==> MinIO: trying ${img}"
  if docker pull -q "$img" >&2; then
    log "==> MinIO: selected ${img}"
    if [[ -n "${GITHUB_ENV:-}" && -w "${GITHUB_ENV}" ]]; then
      echo "MINIO_IMAGE=${img}" >> "$GITHUB_ENV"
    fi
    printf '%s\n' "$img"
    exit 0
  fi
done

log "ERROR: could not pull MinIO from any configured registry mirror"
exit 1
