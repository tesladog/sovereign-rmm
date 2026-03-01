# Backend Unhealthy? Here's The Fix

## What Happened
The backend container started but failed its health check. This is usually an import error or the app crashed on startup.

## Quick Fix

```bash
# 1. Check what went wrong
docker logs rmm-backend

# 2. If you see import errors, rebuild:
docker compose down
docker compose build --no-cache backend
docker compose up -d

# 3. Watch it start
docker compose logs -f backend
```

## Common Issues

### Import Error
```
ModuleNotFoundError: No module named 'routes'
```

**Fix:** The routes/__init__.py file is missing or empty.

```bash
# Make sure it exists
echo "" > backend/routes/__init__.py
docker compose restart backend
```

### Database Connection Error
```
could not translate host name "postgres" to address
```

**Fix:** Backend started before postgres was ready (despite health check).

```bash
docker compose restart backend
```

### Redis Connection Error
```
Error connecting to Redis
```

**Fix:** Check REDIS_PASSWORD in .env matches.

```bash
# Check .env
cat .env | grep REDIS_PASSWORD

# Restart everything
docker compose restart
```

## Test If It's Working

```bash
# Should return healthy
curl http://localhost:8000/api/health

# Should return JSON
docker exec rmm-backend python3 -c "from main import app; print('OK')"
```

## Nuclear Option

If nothing works:

```bash
# Start fresh
docker compose down -v
rm -rf backend/__pycache__ backend/routes/__pycache__
docker compose build --no-cache
docker compose up -d

# Wait 30 seconds for health checks
sleep 30

# Check status
docker compose ps
```

## Success Looks Like

```bash
$ docker compose ps
NAME          STATUS
rmm-backend   Up (healthy)
rmm-postgres  Up (healthy)
rmm-redis     Up (healthy)
rmm-frontend  Up

$ curl http://localhost:8000/api/health
{"status":"healthy","version":"5.0.0"}
```

## Still Failing?

Send me the output of:
```bash
docker logs rmm-backend 2>&1 | head -100
```
