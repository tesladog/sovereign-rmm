# Quick Start Guide

Get up and running in 5 minutes!

## For Administrators (Server Setup)

### 1. Clone and Configure

```bash
git clone https://github.com/yourusername/device-management-system.git
cd device-management-system
cp .env.example .env
```

Edit `.env`:
```env
SECRET_KEY=your-random-secret-here
SERVER_URL=http://your-server-ip:5000
```

### 2. Start Server

```bash
docker-compose up -d
```

### 3. Verify

```bash
curl http://localhost:5000/health
# Should return: {"status":"healthy","timestamp":"..."}
```

Done! Server is running at http://localhost:5000

## For End Users (Agent Installation)

### 1. Download Installer

Get `DeviceManagement.msi` from your IT department or the releases page.

### 2. Install

Double-click the MSI and follow the wizard.

### 3. Verify

The service starts automatically. Check:
```powershell
Get-Service DeviceManagementAgent
```

Done! Your device is now managed.

## First Tasks

### Register a Device

Devices auto-register on first connection, but you can also:

```powershell
cd "C:\Program Files\DeviceManagement"
.\agent.exe --register --server http://your-server:5000
```

### Scan a USB Drive

Just plug it in! The system detects it automatically.

Or scan manually:
```powershell
Invoke-RestMethod -Method Post -Uri "http://server:5000/api/storage/scan" `
    -Body (@{drive_letter="E"} | ConvertTo-Json) `
    -ContentType "application/json"
```

### Create a Sync Job

Via API:
```bash
curl -X POST http://server:5000/api/sync/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Deploy Config",
    "source_path": "/configs/app.conf",
    "destinations": [
      {"device_id": "device-uuid", "path": "C:\\Config\\app.conf"}
    ],
    "mode": "push"
  }'
```

### Generate Asset Tag

```python
python src/utils/asset_tags.py --generate \
  --id SS-2502-0001 \
  --type ssd \
  --size compact \
  --output tag.png
```

## Next Steps

- Read the [Installation Guide](docs/installation.md)
- Explore [Storage Management](docs/storage.md)
- Setup [File Sync](docs/file-sync.md)
- Review [API Documentation](docs/api.md)

## Getting Help

- Check the [docs](docs/)
- File an [issue](https://github.com/yourusername/device-management-system/issues)
- Email: support@example.com
