#!/usr/bin/env bash
# Pick a MinIO image that is pullable from the current network (CI mirrors vary).
set -euo pipefail

TAG="${MINIO_TAG:-RELEASE.2024-12-18T13-15-44Z}"

if [[ -n "${MINIO_IMAGE:-}" ]]; then
  echo "==> MinIO: using MINIO_IMAGE=$MINIO_IMAGE"
  docker pull "$MINIO_IMAGE"
  exit 0
fi

candidates=(
  "mirror.gcr.io/minio/minio:${TAG}"
  "quay.io/minio/minio:${TAG}"
  "minio/minio:${TAG}"
)

for img in "${candidates[@]}"; do
  echo "==> MinIO: trying ${img}"
  if docker pull "$img"; then
    export MINIO_IMAGE="$img"
    echo "==> MinIO: selected ${img}"
    if [[ -n "${GITHUB_ENV:-}" && -w "${GITHUB_ENV}" ]]; then
      echo "MINIO_IMAGE=${img}" >> "$GITHUB_ENV"
    fi
    printf '%s\n' "$img"
    exit 0
  fi
done

echo "ERROR: could not pull MinIO from any configured registry mirror" >&2
exit 1
