#!/bin/bash
# Fix for "Could not resolve host: github.com" error
# This is a CACHED error from a previous build attempt

echo "Cleaning Docker build cache..."

# Stop and remove everything
docker compose down -v 2>/dev/null || true

# Clean ALL build cache
docker builder prune -af

# Remove any old images
docker rmi $(docker images -q rmm-backend 2>/dev/null) 2>/dev/null || true
docker rmi $(docker images -q rmm-frontend 2>/dev/null) 2>/dev/null || true

echo "✓ Cache cleared"
echo ""
echo "Now run:"
echo "  docker compose build --no-cache"
echo "  docker compose up -d"
