# Installation Guide

## Table of Contents
1. [Windows Installation](#windows-installation)
2. [Server Deployment](#server-deployment)
3. [Docker Deployment](#docker-deployment)
4. [Agent Configuration](#agent-configuration)
5. [Troubleshooting](#troubleshooting)

## Windows Installation

### Interactive Installation (Recommended)

1. **Download the MSI installer** from the [Releases](../releases) page

2. **Run the installer**
   - Double-click `DeviceManagement.msi`
   - Follow the installation wizard
   - Choose installation directory (default: `C:\Program Files\DeviceManagement`)
   - The service will start automatically after installation

3. **Verify installation**
   ```powershell
   # Check service status
   Get-Service DeviceManagementAgent
   
   # View agent logs
   Get-Content "C:\Program Files\DeviceManagement\agent.log" -Tail 20
   ```

### Silent Installation (Windows Server / Automated Deployment)

For unattended installation on Windows Server or via deployment tools:

```batch
:: Install silently
msiexec /i DeviceManagement.msi /quiet /norestart /log install.log

:: Install with custom server URL
msiexec /i DeviceManagement.msi /quiet SERVER_URL="http://your-server:5000"

:: Install to custom directory
msiexec /i DeviceManagement.msi /quiet INSTALLFOLDER="D:\DeviceManagement"

:: Uninstall silently
msiexec /x DeviceManagement.msi /quiet /norestart
```

### Group Policy Deployment

To deploy via Group Policy (GPO):

1. Copy MSI to network share: `\\server\share\DeviceManagement.msi`
2. Open Group Policy Management
3. Create or edit a GPO
4. Navigate to: Computer Configuration → Policies → Software Settings → Software Installation
5. Right-click → New → Package
6. Select the MSI file
7. Choose "Assigned" for automatic installation

### SCCM/ConfigMgr Deployment

```powershell
# Create application in ConfigMgr
New-CMApplication -Name "Device Management Agent" -Publisher "Your Company"

# Add deployment type
Add-CMDeploymentType -ApplicationName "Device Management Agent" `
    -MsiInstaller -ContentLocation "\\server\share\DeviceManagement.msi" `
    -InstallCommand "msiexec /i DeviceManagement.msi /quiet" `
    -UninstallCommand "msiexec /x DeviceManagement.msi /quiet"
```

## Server Deployment

### Prerequisites

- Linux server (Ubuntu 20.04+ recommended)
- Docker and Docker Compose
- 2GB RAM minimum
- 10GB disk space

### Quick Start with Docker

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/device-management-system.git
   cd device-management-system
   ```

2. **Configure environment**
   ```bash
   cp .env.example .env
   nano .env
   ```
   
   Edit the following:
   ```env
   SECRET_KEY=your-random-secret-key-here
   DATABASE_URL=sqlite:///data/devices.db
   SERVER_URL=http://your-server-ip:5000
   ```

3. **Start services**
   ```bash
   docker-compose up -d
   ```

4. **Verify deployment**
   ```bash
   # Check service status
   docker-compose ps
   
   # View logs
   docker-compose logs -f server
   
   # Test API
   curl http://localhost:5000/health
   ```

### Manual Installation (Without Docker)

1. **Install dependencies**
   ```bash
   sudo apt-get update
   sudo apt-get install -y python3.10 python3-pip postgresql
   ```

2. **Setup Python environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Configure database**
   ```bash
   # For PostgreSQL
   sudo -u postgres createdb devicemanagement
   export DATABASE_URL="postgresql://user:pass@localhost/devicemanagement"
   
   # For SQLite (default)
   export DATABASE_URL="sqlite:///data/devices.db"
   ```

4. **Initialize database**
   ```bash
   python src/server/app.py --init-db
   ```

5. **Create systemd service**
   ```bash
   sudo nano /etc/systemd/system/devicemanagement.service
   ```
   
   ```ini
   [Unit]
   Description=Device Management Server
   After=network.target
   
   [Service]
   Type=simple
   User=devicemgmt
   WorkingDirectory=/opt/device-management-system
   Environment="DATABASE_URL=sqlite:///data/devices.db"
   Environment="SECRET_KEY=your-secret-key"
   ExecStart=/opt/device-management-system/venv/bin/python src/server/app.py
   Restart=always
   
   [Install]
   WantedBy=multi-user.target
   ```
   
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable devicemanagement
   sudo systemctl start devicemanagement
   ```

## Docker Deployment

### Development Environment

```bash
# Start with hot reload
docker-compose -f docker-compose.dev.yml up

# Run tests
docker-compose run --rm server pytest

# Shell access
docker-compose exec server bash
```

### Production Deployment

```bash
# Use production compose file
docker-compose -f docker-compose.prod.yml up -d

# Scale services
docker-compose -f docker-compose.prod.yml up -d --scale server=3

# Update without downtime
docker-compose pull
docker-compose up -d --no-deps --build server
```

### Behind Reverse Proxy (Nginx)

```nginx
server {
    listen 80;
    server_name devices.example.com;
    
    location / {
        proxy_pass http://localhost:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

## Agent Configuration

### Configuration File

The agent uses `agent_config.json`:

```json
{
  "device_id": "auto-generated-on-first-run",
  "server_url": "http://your-server:5000",
  "heartbeat_interval": 30,
  "storage_scan_depth": 3,
  "auto_register": true
}
```

### Environment Variables

```batch
:: Windows
set SERVER_URL=http://your-server:5000
set LOG_LEVEL=INFO

:: Linux
export SERVER_URL=http://your-server:5000
export LOG_LEVEL=INFO
```

### Manual Registration

If auto-registration fails:

```powershell
cd "C:\Program Files\DeviceManagement"
.\agent.exe --register --server http://your-server:5000
```

## Troubleshooting

### Permission Denied Error (MSI Build)

If you encounter the permission error during build:

```bash
# Fix permissions before building
chmod -R 755 pybundle/python-embed/
python build_msi.py
```

### Agent Not Connecting

1. **Check firewall**
   ```powershell
   # Allow outbound connections
   New-NetFirewallRule -DisplayName "Device Management Agent" `
       -Direction Outbound -Protocol TCP -LocalPort 5000 -Action Allow
   ```

2. **Verify server URL**
   ```powershell
   curl http://your-server:5000/health
   ```

3. **Check service status**
   ```powershell
   Get-Service DeviceManagementAgent
   Get-EventLog -LogName Application -Source "DeviceManagementAgent" -Newest 20
   ```

### Container Exits Immediately

Check Docker logs:
```bash
docker-compose logs server

# Common issues:
# 1. Database connection failed
# 2. Port already in use
# 3. Missing environment variables

# Fix: Check .env file and port availability
netstat -tulpn | grep 5000
```

### Storage Not Detected

1. **Verify USB monitoring is running**
   ```powershell
   # Check agent logs
   Get-Content "C:\Program Files\DeviceManagement\agent.log" | Select-String "USB monitoring"
   ```

2. **Manual scan**
   ```powershell
   # Trigger manual scan via API
   Invoke-RestMethod -Method Post -Uri "http://server:5000/api/storage/scan" `
       -Body (@{drive_letter="E"} | ConvertTo-Json) `
       -ContentType "application/json"
   ```

### Group Policy Not Updating

1. **Check permissions**
   ```powershell
   # Agent needs to run as SYSTEM or with appropriate permissions
   Get-Service DeviceManagementAgent | Select-Object Name, StartType, Status, StartName
   ```

2. **Manual gpresult test**
   ```powershell
   gpresult /r
   # Verify the command works manually
   ```

### High Resource Usage

1. **Adjust scan depth**
   ```json
   // In agent_config.json
   {
     "storage_scan_depth": 2  // Reduce from 3 to 2
   }
   ```

2. **Increase heartbeat interval**
   ```json
   {
     "heartbeat_interval": 60  // Increase from 30 to 60 seconds
   }
   ```

## Next Steps

- [Configuration Guide](configuration.md)
- [API Documentation](api.md)
- [Storage Management](storage.md)
- [File Sync Setup](file-sync.md)

## Support

For additional help:
- GitHub Issues: [Report a bug](https://github.com/yourusername/device-management-system/issues)
- Email: support@example.com
- Documentation: [Full docs](https://docs.example.com)
