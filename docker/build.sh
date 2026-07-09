#!/bin/bash
set -e
cd "$(dirname "$0")/.."

IMAGE="yapo:latest"
ARCHIVE="docker/yapo.tar.gz"

echo "Generating config.toml.j2"
python docker//convert-config.py < ./config.toml > docker/config.toml.j2

echo "Building $IMAGE..."
docker build -t "$IMAGE" -f docker/Dockerfile .

echo "Exporting to $ARCHIVE using pigz (parallel compression with all cores)..."
docker save "$IMAGE" | pigz -1 -p $(nproc) > "$ARCHIVE"

docker image prune -f

echo "Done: $ARCHIVE ($(du -h $ARCHIVE | cut -f1))"
