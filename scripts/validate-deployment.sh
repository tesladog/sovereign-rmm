#!/bin/bash
# Docker Deployment Validation Script
# Checks all containers and reports issues

set -e

COMPOSE_FILE="${1:-docker-compose.yml}"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=================================="
echo "Docker Deployment Validation"
echo "=================================="
echo ""
echo "Compose file: $COMPOSE_FILE"
echo ""

# Check if Docker is running
echo "Checking Docker..."
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}✗ Docker is not running${NC}"
    exit 1
else
    echo -e "${GREEN}✓ Docker is running${NC}"
fi

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}✗ docker-compose not found${NC}"
    exit 1
else
    echo -e "${GREEN}✓ docker-compose found${NC}"
fi

# Validate compose file
echo ""
echo "Validating compose file..."
if docker-compose -f "$COMPOSE_FILE" config > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Compose file is valid${NC}"
else
    echo -e "${RED}✗ Compose file has errors${NC}"
    docker-compose -f "$COMPOSE_FILE" config
    exit 1
fi

# Check if .env file exists
if [ ! -f .env ]; then
    echo -e "${YELLOW}⚠ .env file not found${NC}"
    echo "  Creating from .env.example..."
    cp .env.example .env
    echo -e "${YELLOW}  Please edit .env before deploying${NC}"
fi

# Check SECRET_KEY
if grep -q "change-me" .env 2>/dev/null; then
    echo -e "${YELLOW}⚠ SECRET_KEY is using default value${NC}"
    echo "  Generate a random secret key!"
fi

# Start containers if not running
echo ""
echo "Starting containers..."
docker-compose -f "$COMPOSE_FILE" up -d

# Wait for containers to start
echo ""
echo "Waiting for containers to be ready..."
sleep 10

# Check container status
echo ""
echo "Checking container status..."
CONTAINERS=$(docker-compose -f "$COMPOSE_FILE" ps -q)

ALL_HEALTHY=true
for container in $CONTAINERS; do
    NAME=$(docker inspect --format='{{.Name}}' "$container" | sed 's/\///')
    STATUS=$(docker inspect --format='{{.State.Status}}' "$container")
    HEALTH=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container")
    
    if [ "$STATUS" != "running" ]; then
        echo -e "${RED}✗ $NAME: $STATUS${NC}"
        ALL_HEALTHY=false
    elif [ "$HEALTH" = "unhealthy" ]; then
        echo -e "${RED}✗ $NAME: running but unhealthy${NC}"
        ALL_HEALTHY=false
    elif [ "$HEALTH" = "starting" ]; then
        echo -e "${YELLOW}⚠ $NAME: starting${NC}"
    elif [ "$HEALTH" = "healthy" ] || [ "$HEALTH" = "none" ]; then
        echo -e "${GREEN}✓ $NAME: running${NC}"
    fi
done

# Check server health endpoint
echo ""
echo "Checking API health..."
if curl -sf http://localhost:5000/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓ API health check passed${NC}"
    curl -s http://localhost:5000/health | python -m json.tool 2>/dev/null || echo "  (Response: OK)"
else
    echo -e "${RED}✗ API health check failed${NC}"
    echo "  Checking logs..."
    docker-compose -f "$COMPOSE_FILE" logs --tail=20 server
    ALL_HEALTHY=false
fi

# Check database connectivity (if using PostgreSQL)
if docker-compose -f "$COMPOSE_FILE" ps | grep -q postgres; then
    echo ""
    echo "Checking database connectivity..."
    if docker-compose -f "$COMPOSE_FILE" exec -T postgres pg_isready > /dev/null 2>&1; then
        echo -e "${GREEN}✓ PostgreSQL is ready${NC}"
    else
        echo -e "${RED}✗ PostgreSQL is not ready${NC}"
        ALL_HEALTHY=false
    fi
fi

# Check Redis connectivity (if using Redis)
if docker-compose -f "$COMPOSE_FILE" ps | grep -q redis; then
    echo ""
    echo "Checking Redis connectivity..."
    if docker-compose -f "$COMPOSE_FILE" exec -T redis redis-cli ping > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Redis is ready${NC}"
    else
        echo -e "${RED}✗ Redis is not ready${NC}"
        ALL_HEALTHY=false
    fi
fi

# Check port availability
echo ""
echo "Checking port availability..."
PORTS=(5000)
for port in "${PORTS[@]}"; do
    if nc -z localhost "$port" 2>/dev/null; then
        echo -e "${GREEN}✓ Port $port is accessible${NC}"
    else
        echo -e "${RED}✗ Port $port is not accessible${NC}"
        ALL_HEALTHY=false
    fi
done

# Check volumes
echo ""
echo "Checking volumes..."
VOLUMES=$(docker volume ls --filter name=device-management --format "{{.Name}}")
for volume in $VOLUMES; do
    echo -e "${GREEN}✓ $volume${NC}"
done

# Check disk space
echo ""
echo "Checking disk space..."
DISK_USAGE=$(df -h . | awk 'NR==2 {print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -gt 90 ]; then
    echo -e "${RED}✗ Disk usage is ${DISK_USAGE}% (critical)${NC}"
    ALL_HEALTHY=false
elif [ "$DISK_USAGE" -gt 80 ]; then
    echo -e "${YELLOW}⚠ Disk usage is ${DISK_USAGE}% (warning)${NC}"
else
    echo -e "${GREEN}✓ Disk usage is ${DISK_USAGE}%${NC}"
fi

# Check memory usage
echo ""
echo "Checking container memory usage..."
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}"

# Final summary
echo ""
echo "=================================="
if [ "$ALL_HEALTHY" = true ]; then
    echo -e "${GREEN}✓ All checks passed!${NC}"
    echo ""
    echo "Services are running at:"
    echo "  - API:  http://localhost:5000"
    echo "  - Docs: http://localhost:5000/docs (if implemented)"
    echo ""
    echo "Next steps:"
    echo "  1. Install Windows agent on client machines"
    echo "  2. Configure devices to connect to this server"
    echo "  3. Monitor logs: docker-compose logs -f"
    echo ""
else
    echo -e "${RED}✗ Some checks failed${NC}"
    echo ""
    echo "Troubleshooting:"
    echo "  1. Check logs: docker-compose -f $COMPOSE_FILE logs"
    echo "  2. Verify .env configuration"
    echo "  3. Check firewall settings"
    echo "  4. See docs/docker-deployment.md for more help"
    echo ""
    exit 1
fi
