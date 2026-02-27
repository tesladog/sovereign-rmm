# Docker Deployment Guide

## All Issues Fixed ✅

### Problems Identified and Resolved:

1. **Missing Dockerfile.web** - Removed non-existent web service from compose
2. **No health check dependencies** - Added proper `depends_on` with conditions
3. **SQLite file locking** - Added PostgreSQL option for multi-container deployments
4. **No Redis for WebSocket scaling** - Added Redis service
5. **Missing security** - Added non-root user, read-only volumes
6. **No resource limits** - Added CPU/memory limits
7. **Missing nginx reverse proxy** - Added with SSL support
8. **Incomplete healthchecks** - Improved all health checks
9. **No separation of concerns** - Created multiple compose files for different uses
10. **Missing .dockerignore** - Added to reduce image size

## Quick Start

### Option 1: Simple (SQLite)
For testing or small deployments:
```bash
docker-compose -f docker-compose.simple.yml up -d
```

### Option 2: Development (with debugging)
For local development with hot reload:
```bash
docker-compose -f docker-compose.dev.yml up
```

### Option 3: Production (PostgreSQL + Redis + Nginx)
For production deployments:
```bash
docker-compose up -d
```

## Deployment Options Explained

### 1. Simple Deployment (docker-compose.simple.yml)

**Uses:**
- SQLite database
- No external dependencies
- Minimal resource usage

**Best for:**
- Testing
- Small deployments (< 10 devices)
- Single server setups

**Start:**
```bash
docker-compose -f docker-compose.simple.yml up -d
```

**Access:** http://localhost:5000

### 2. Development Deployment (docker-compose.dev.yml)

**Features:**
- Hot code reload
- Debug port exposed (5678)
- Database admin UI (Adminer)
- All ports exposed for tools
- Verbose logging

**Best for:**
- Local development
- Testing new features
- Debugging issues

**Start:**
```bash
docker-compose -f docker-compose.dev.yml up
# Or in background:
docker-compose -f docker-compose.dev.yml up -d
```

**Access:**
- API: http://localhost:5000
- Database Admin: http://localhost:8080
- Redis: localhost:6379
- PostgreSQL: localhost:5432

### 3. Production Deployment (docker-compose.yml)

**Features:**
- PostgreSQL database (scalable, reliable)
- Redis for WebSocket scaling
- Nginx reverse proxy with SSL
- Resource limits
- Proper health checks
- Security hardening

**Best for:**
- Production deployments
- Multiple servers
- High availability setups
- > 10 devices

**Start:**
```bash
# Copy and edit environment file
cp .env.example .env
nano .env

# Start services
docker-compose up -d
```

**Access:**
- HTTP: http://localhost (redirects to HTTPS)
- HTTPS: https://localhost

## Configuration

### Environment Variables

Edit `.env` file:

```bash
# Required
SECRET_KEY=generate-random-string-here
DATABASE_URL=postgresql://devicemgmt:changeme@postgres:5432/devicemanagement

# Optional
SERVER_PORT=5000
LOG_LEVEL=INFO
TZ=America/New_York
```

### Generate Secret Key

```bash
# Linux/Mac
openssl rand -base64 32

# Python
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### SSL Certificates

For HTTPS in production:

```bash
# Create SSL directory
mkdir -p docker/ssl

# Self-signed certificate (for testing)
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout docker/ssl/key.pem \
  -out docker/ssl/cert.pem

# For production, use Let's Encrypt:
# Place cert.pem and key.pem in docker/ssl/
```

## Container Management

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f server

# Last 100 lines
docker-compose logs --tail=100 server
```

### Check Status

```bash
# All containers
docker-compose ps

# Health check status
docker-compose ps --format "table {{.Name}}\t{{.Status}}"
```

### Restart Services

```bash
# All services
docker-compose restart

# Specific service
docker-compose restart server

# Recreate container
docker-compose up -d --force-recreate server
```

### Stop and Remove

```bash
# Stop all
docker-compose stop

# Stop and remove containers (data preserved)
docker-compose down

# Remove everything including volumes (WARNING: deletes data)
docker-compose down -v
```

### Update Containers

```bash
# Pull latest images
docker-compose pull

# Rebuild and restart
docker-compose up -d --build
```

## Troubleshooting

### Container Exits Immediately

**Check logs:**
```bash
docker-compose logs server
```

**Common causes:**
1. Missing environment variables
2. Database connection failed
3. Port already in use
4. Permission issues

**Fix:**
```bash
# Check environment
docker-compose config

# Verify ports are free
sudo netstat -tulpn | grep -E "5000|5432|6379"

# Check permissions
ls -la data/ logs/

# Fix permissions
sudo chown -R $USER:$USER data/ logs/ uploads/
```

### Database Connection Failed

**PostgreSQL not ready:**
```bash
# Check postgres health
docker-compose ps postgres

# View postgres logs
docker-compose logs postgres

# Restart postgres
docker-compose restart postgres
```

**Wrong credentials:**
```bash
# Verify .env settings
cat .env | grep POSTGRES

# Test connection
docker-compose exec server python -c "
from sqlalchemy import create_engine
import os
engine = create_engine(os.getenv('DATABASE_URL'))
print('Connection successful!' if engine else 'Failed')
"
```

### Port Already in Use

**Find what's using the port:**
```bash
sudo lsof -i :5000
# or
sudo netstat -tulpn | grep 5000
```

**Change port in .env:**
```bash
SERVER_PORT=5001
```

**Or kill the process:**
```bash
sudo kill -9 <PID>
```

### Health Check Failing

**Check endpoint manually:**
```bash
docker-compose exec server curl http://localhost:5000/health
```

**Increase timeout:**
Edit `docker-compose.yml`:
```yaml
healthcheck:
  start_period: 60s  # Increase from 40s
  timeout: 15s       # Increase from 10s
```

### Out of Memory

**Check resource usage:**
```bash
docker stats
```

**Increase limits in docker-compose.yml:**
```yaml
deploy:
  resources:
    limits:
      memory: 2G  # Increase from 1G
```

### Container Can't Access Internet

**Check DNS:**
```bash
docker-compose exec server ping google.com
```

**Fix DNS in docker-compose.yml:**
```yaml
services:
  server:
    dns:
      - 8.8.8.8
      - 8.8.4.4
```

## Performance Tuning

### PostgreSQL Optimization

Create `docker/postgres.conf`:
```ini
max_connections = 100
shared_buffers = 256MB
effective_cache_size = 1GB
work_mem = 4MB
maintenance_work_mem = 64MB
```

Mount in docker-compose.yml:
```yaml
postgres:
  volumes:
    - ./docker/postgres.conf:/etc/postgresql/postgresql.conf
  command: postgres -c config_file=/etc/postgresql/postgresql.conf
```

### Redis Optimization

```yaml
redis:
  command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
```

### Nginx Caching

Add to nginx.conf:
```nginx
proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=api_cache:10m max_size=100m;

location /api/ {
    proxy_cache api_cache;
    proxy_cache_valid 200 5m;
    add_header X-Cache-Status $upstream_cache_status;
}
```

## Backup and Restore

### Backup Database

**PostgreSQL:**
```bash
# Backup
docker-compose exec postgres pg_dump -U devicemgmt devicemanagement > backup.sql

# Restore
cat backup.sql | docker-compose exec -T postgres psql -U devicemgmt devicemanagement
```

**SQLite:**
```bash
# Backup
docker-compose exec server sqlite3 /app/data/devices.db ".backup /app/data/backup.db"
cp data/backup.db backup.db

# Restore
cp backup.db data/devices.db
```

### Backup Volumes

```bash
# Create backup directory
mkdir -p backups

# Backup all data
docker run --rm \
  -v device-management-system_data:/data \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/data-backup-$(date +%Y%m%d).tar.gz /data
```

## Scaling

### Multiple Server Instances

```bash
# Scale server to 3 instances
docker-compose up -d --scale server=3

# Nginx will load balance automatically
```

### Multiple Sync Coordinators

```bash
docker-compose up -d --scale sync-coordinator=2
```

## Monitoring

### Container Stats

```bash
# Real-time stats
docker stats

# JSON format
docker stats --no-stream --format "{{json .}}"
```

### Log Aggregation

Use Docker logging drivers:
```yaml
services:
  server:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

## Security Best Practices

1. **Change default passwords** in `.env`
2. **Use SSL certificates** for production
3. **Keep images updated**: `docker-compose pull`
4. **Limit exposed ports** - only expose what's needed
5. **Use secrets** for sensitive data:
```yaml
secrets:
  db_password:
    file: ./secrets/db_password.txt
```

## Next Steps

- Set up monitoring (Prometheus + Grafana)
- Configure automated backups
- Set up log aggregation (ELK stack)
- Implement CI/CD pipeline
- Add health monitoring alerts
