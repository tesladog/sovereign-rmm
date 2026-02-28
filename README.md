# Sovereign RMM - Complete System

## Quick Start

```bash
# 1. Clone or copy files
cd sovereign-rmm-complete

# 2. Edit .env (change passwords!)
nano .env

# 3. Start
docker compose up -d

# 4. Access
Dashboard: http://your-server:8080
API: http://your-server:8000
```

## Features

- ✅ Multi-platform agents (Windows, Linux, Android)
- ✅ Real-time device monitoring
- ✅ Script execution
- ✅ Update management
- ✅ Device lockdown
- ✅ Storage tracking
- ✅ Beautiful dark theme UI

## Structure

```
sovereign-rmm-complete/
├── compose.yaml       # Docker config
├── .env              # Configuration
├── backend/          # FastAPI backend
│   ├── Dockerfile
│   ├── main.py
│   ├── models.py
│   ├── database.py
│   └── routes/
└── frontend/         # Nginx + HTML
    ├── Dockerfile
    ├── nginx.conf
    └── index.html
```

## Troubleshooting

### DNS Issues
```bash
echo '{"dns": ["8.8.8.8", "8.8.4.4"]}' | sudo tee /etc/docker/daemon.json
sudo systemctl restart docker
```

### Check Status
```bash
docker compose ps
docker compose logs -f backend
curl http://localhost:8000/api/health
```

## License

MIT - Free to use
