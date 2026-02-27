#!/bin/bash
# Setup script for Device Management System

set -e

echo "=================================="
echo "Device Management System Setup"
echo "=================================="
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then 
    echo "Please do not run as root"
    exit 1
fi

# Check prerequisites
echo "Checking prerequisites..."

# Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker not found. Please install Docker first."
    exit 1
else
    echo "✓ Docker found"
fi

# Docker Compose
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose not found. Please install Docker Compose first."
    exit 1
else
    echo "✓ Docker Compose found"
fi

echo ""
echo "Creating directories..."
mkdir -p data logs uploads sync-storage

echo ""
echo "Setting up environment..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "✓ Created .env file"
    echo "⚠ Please edit .env and set your configuration"
else
    echo "✓ .env already exists"
fi

echo ""
echo "Generating secret key..."
SECRET_KEY=$(openssl rand -base64 32)
if grep -q "SECRET_KEY=change-me" .env; then
    sed -i "s/SECRET_KEY=change-me/SECRET_KEY=$SECRET_KEY/" .env
    echo "✓ Secret key generated"
else
    echo "✓ Secret key already set"
fi

echo ""
echo "Starting services..."
docker-compose pull
docker-compose up -d

echo ""
echo "Waiting for services to start..."
sleep 10

# Check health
if curl -sf http://localhost:5000/health > /dev/null; then
    echo "✓ Server is healthy"
else
    echo "⚠ Server may not be ready yet. Check logs with: docker-compose logs"
fi

echo ""
echo "=================================="
echo "Setup complete!"
echo "=================================="
echo ""
echo "Server URL: http://localhost:5000"
echo ""
echo "Next steps:"
echo "1. Edit .env file with your configuration"
echo "2. Restart services: docker-compose restart"
echo "3. Install agent on Windows machines"
echo "4. Access web UI: http://localhost:3000 (when implemented)"
echo ""
echo "Commands:"
echo "  View logs:    docker-compose logs -f"
echo "  Stop:         docker-compose down"
echo "  Restart:      docker-compose restart"
echo ""
