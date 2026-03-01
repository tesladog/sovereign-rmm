# 🖥️ Sovereign RMM

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?style=flat&logo=docker&logoColor=white)](https://www.docker.com/)

**Self-hosted Remote Monitoring & Management**  
Free alternative to Action1, N-able, ConnectWise

## ✨ Features

🖥️ Multi-Platform (Windows, Linux, Android) • 📊 Real-Time Monitoring • 🔒 Device Lockdown  
📦 Update Management • 📜 Script Execution • 💾 Software Inventory • 🌐 WebSocket Updates

## 🚀 Quick Start

```bash
git clone https://github.com/tesladog/sovereign-rmm.git
cd sovereign-rmm
cp .env.example .env
nano .env  # Change passwords!
docker compose up -d
```

Access: http://localhost:8080

## 📦 What's Included

- FastAPI backend with PostgreSQL & Redis
- Beautiful dark theme dashboard
- Windows/Linux/Android agents
- Complete REST API + WebSocket
- Device lockdown, updates, scripts, inventory

## 🔧 Agent Install

```powershell
# Windows
$env:SERVER_URL="http://your-server:8000"
python agent-windows/windows_agent.py
```

## 📝 License

MIT - Free for any use

⭐ **Star if useful!**
