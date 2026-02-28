# Sovereign RMM v5 - Complete Action1-Style RMM

## 🚀 Quick Start (Docker)

```bash
# 1. Clone your repo
git clone https://github.com/tesladog/sovereign-rmm.git
cd sovereign-rmm

# 2. Create .env
cp .env.example .env
nano .env  # Edit with your settings

# 3. Generate secure token
openssl rand -hex 32  # Use this for AGENT_TOKEN

# 4. Start server
docker compose up -d

# 5. Access
Dashboard: http://your-server:3000
API: http://your-server:8000
```

## 📦 What's New in v5

### Multi-Platform Support
- ✅ Windows (MSI)
- ✅ Linux (DEB)
- ✅ Android (APK)
- ✅ Auto-dependency installation

### Update Management
- ✅ Centralized update caching
- ✅ Approve/decline workflow
- ✅ Base image deployment
- ✅ Real-time progress
- ✅ Severity tracking

### Device Lockdown
- ✅ Individual device lockdown
- ✅ Global emergency lockdown
- ✅ Configurable rules
- ✅ Violation tracking

### Enhanced Monitoring
- ✅ Software inventory
- ✅ Process monitoring
- ✅ Hardware statistics
- ✅ Network stats

### Auto-Installer Generation
- ✅ Build MSI, DEB, APK from dashboard
- ✅ No external tools needed
- ✅ Embedded dependencies

## 🎯 Use Cases

### Software Deployment
1. Define base image: "All Windows PCs need Chrome 120+"
2. Server finds devices without Chrome 120
3. Download Chrome installer once
4. Deploy to all devices from cache
5. Track installation progress

### Emergency Lockdown
1. Laptop reported stolen
2. Click "Lockdown Device" in dashboard
3. Device immediately locks down
4. Cannot access network, USB disabled
5. All actions logged

### Update Management
1. Windows updates detected
2. Server caches update files
3. Admin reviews in dashboard
4. Approve critical updates
5. Decline optional updates
6. Auto-install on all devices
7. Only downloads once

## 📋 Configuration (.env)

```env
# Database
POSTGRES_DB=sovereignrmm
POSTGRES_USER=rmmuser
POSTGRES_PASSWORD=SECURE_PASSWORD_HERE

# Redis
REDIS_PASSWORD=SECURE_PASSWORD_HERE

# Server
SERVER_IP=192.168.1.100  # Your server IP
BACKEND_PORT=8000
DASHBOARD_PORT=3000

# Security
AGENT_TOKEN=64_CHAR_RANDOM_TOKEN_HERE  # openssl rand -hex 32
ADMIN_USERNAME=admin
ADMIN_PASSWORD=SECURE_PASSWORD_HERE
```

## 🛠️ Agent Installation

### Windows
```powershell
# Download from dashboard: http://your-server:3000/downloads
msiexec /i SovereignAgent.msi /quiet
```

### Linux (Ubuntu/Debian)
```bash
# Download DEB from dashboard
sudo dpkg -i sovereign-agent.deb
# Dependencies auto-install
```

### Android
```bash
# Download APK from dashboard
adb install sovereign-agent.apk
# Or install from file manager
```

## 📊 Dashboard Features

### Overview
- Device count (online/offline)
- Pending updates
- Active lockdowns
- Recent violations
- Network usage

### Device Management
- Hardware specs
- Software inventory
- Running processes
- Pending updates
- Lockdown status

### Update Management
- Available updates list
- Approval queue
- Installation progress
- Base image config
- Update policies

### Lockdown Control
- Create lockdown rules
- Emergency lockdown button
- Violation log
- Device-specific lockdown

## 🔌 API Examples

### Approve Update
```bash
curl -X POST http://server:8000/api/updates/UPDATE_ID/approve \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Lockdown Device
```bash
curl -X POST http://server:8000/api/lockdown/device/DEVICE_ID \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Get Software Inventory
```bash
curl http://server:8000/api/software/DEVICE_ID \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## 🔧 Troubleshooting

### Server Issues
```bash
# Check logs
docker compose logs -f backend

# Restart services
docker compose restart

# Check health
curl http://localhost:8000/api/health
```

### Agent Connection Issues
```powershell
# Windows - Check service
Get-Service SovereignRMMAgent

# Check logs
Get-Content C:\ProgramData\SovereignRMM\agent.log
```

```bash
# Linux - Check service
sudo systemctl status sovereign-rmm-agent

# Check logs
sudo journalctl -u sovereign-rmm-agent -f
```

## 🔒 Security

- JWT authentication
- Agent token validation
- TLS/SSL support ready
- File integrity verification
- Audit logging
- Password hashing (bcrypt)

## 📈 Scaling

### Horizontal Scaling
```yaml
# Add to compose.yaml
backend:
  deploy:
    replicas: 3
```

### Load Balancer
```nginx
upstream backend {
    server backend-1:8000;
    server backend-2:8000;
    server backend-3:8000;
}
```

## 🆕 What's Different from Action1

| Feature | Action1 | Sovereign RMM |
|---------|---------|---------------|
| Cost | $$ Subscription | Free (Self-hosted) |
| Devices | Limited | Unlimited |
| Data | Cloud | Your server |
| Customization | Limited | Full control |
| Updates | Auto | Manual approval |
| Open Source | No | Yes |

## 📝 License

MIT License - Free for any use

## 🤝 Contributing

See FEATURES_ADDED.md for complete feature list

## 🆘 Support

- GitHub Issues: https://github.com/tesladog/sovereign-rmm/issues
- Documentation: See /docs folder
