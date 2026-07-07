#!/bin/bash
set -e
cd "$(dirname "$0")/.."

IMAGE="yapo:latest"
ARCHIVE="docker/yapo.tar.gz"

echo "Building $IMAGE..."
docker build -t "$IMAGE" -f docker/Dockerfile .

echo "Exporting to $ARCHIVE..."
docker save "$IMAGE" | gzip > "$ARCHIVE"

docker image prune -f

echo "Done: $ARCHIVE ($(du -h $ARCHIVE | cut -f1))"
