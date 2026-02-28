# Sovereign RMM - COMPLETE & READY

## Deploy in 3 Commands

```bash
docker compose up -d
```

That's it. Done.

## Access

- Dashboard: http://your-server:8080
- API: http://your-server:8000

## What You Get

✅ PostgreSQL database
✅ Redis cache
✅ FastAPI backend
✅ Beautiful dark UI
✅ Real-time WebSocket
✅ Device management
✅ Ready for agents

## Configuration

Edit `.env` before deploying:
- Change all passwords
- Set SERVER_IP to your actual IP
- Keep AGENT_TOKEN secure

## Troubleshooting

### Build fails
```bash
echo '{"dns": ["8.8.8.8"]}' | sudo tee /etc/docker/daemon.json
sudo systemctl restart docker
```

### Check status
```bash
docker compose ps
docker compose logs -f
curl http://localhost:8000/api/health
```

## Done.
