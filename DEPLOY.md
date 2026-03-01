# DEPLOY - Exact Commands

## The Error You're Seeing

```
Could not resolve host: github.com
```

**This is a CACHED error** from when the compose.yaml was trying to pull from GitHub. 

The current compose.yaml is correct (builds locally), but Docker cached the old GitHub URL.

## Fix It

Run these commands **exactly**:

```bash
# 1. Clean Docker cache
docker compose down -v
docker builder prune -af

# 2. Build fresh (no cache)
docker compose build --no-cache

# 3. Start
docker compose up -d

# 4. Check
docker compose ps
curl http://localhost:8000/api/health
```

## If That Doesn't Work

The absolutely guaranteed way:

```bash
# 1. Stop everything
docker compose down -v
docker system prune -af --volumes

# 2. Restart Docker
sudo systemctl restart docker

# 3. Build and start
docker compose build --no-cache
docker compose up -d
```

## Verify compose.yaml is Correct

```bash
cat compose.yaml | grep "context:"
```

Should show:
```
context: .
```

NOT:
```
context: https://github.com/...
```

## Quick Test

```bash
# Test if backend Dockerfile exists
ls -la backend/Dockerfile

# Test if it can read it
cat backend/Dockerfile | head -5
```

## Still Failing?

Check DNS:
```bash
# Fix Docker DNS
echo '{"dns": ["8.8.8.8", "8.8.4.4"]}' | sudo tee /etc/docker/daemon.json
sudo systemctl restart docker

# Try again
docker compose build --no-cache
docker compose up -d
```

## Success Looks Like

```bash
$ docker compose ps
NAME           IMAGE         STATUS
rmm-postgres   postgres:16   Up (healthy)
rmm-redis      redis:7       Up (healthy)
rmm-backend    rmm-backend   Up (healthy)
rmm-frontend   rmm-frontend  Up

$ curl http://localhost:8000/api/health
{"status":"healthy","version":"5.0.0"}
```

## That's It

Access: http://your-server:8080
