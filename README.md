# Device Management System

A comprehensive Windows device and storage management system with automated deployment, asset tracking, and file synchronization capabilities.

## Features

- 🖥️ **Device Management**: Track laptops, desktops, and servers
- 💾 **Storage Tracking**: Persistent identification of external drives (HDD/SSD/USB)
- 🔄 **File Sync**: Push and sync files across devices (Syncthing-style)
- 📋 **Group Policy Monitoring**: Track gpupdate status and pending restarts
- 🔌 **USB Auto-Detection**: Automatic folder tree scanning on drive insertion
- 🏷️ **Asset Tagging**: Generate both standard and compact labels
- 📦 **MSI Installer**: Interactive Windows installer with Server compatibility
- 🐳 **Docker Support**: Containerized deployment with persistence

## Quick Start

### Windows Installation (Interactive)

1. Download the latest MSI from [Releases](releases)
2. Run the installer and follow the setup wizard
3. The service will start automatically

### Server Deployment (Silent)

```bash
msiexec /i DeviceManagement.msi /quiet /norestart
```

### Docker Deployment

```bash
docker-compose up -d
```

## System Requirements

- Windows 10/11 or Windows Server 2016+
- .NET Framework 4.8 or higher
- 2GB RAM minimum
- 500MB disk space

## Configuration

See [docs/configuration.md](docs/configuration.md) for detailed setup instructions.

## Architecture

- **Backend**: Python Flask API
- **Frontend**: React web UI
- **Agent**: Windows service (Python)
- **Database**: SQLite with optional PostgreSQL
- **Sync Engine**: Custom file synchronization

## Documentation

- [Installation Guide](docs/installation.md)
- [Configuration](docs/configuration.md)
- [API Reference](docs/api.md)
- [Storage Management](docs/storage.md)
- [File Sync](docs/file-sync.md)
- [Asset Tags](docs/asset-tags.md)

## Development

```bash
# Clone the repository
git clone https://github.com/yourusername/device-management-system.git
cd device-management-system

# Install dependencies
pip install -r requirements.txt
npm install

# Run development server
python src/server/app.py

# Run agent locally
python src/agent/agent.py
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.

## License

MIT License - see [LICENSE](LICENSE)

## Support

- 📧 Email: support@example.com
- 🐛 Issues: [GitHub Issues](issues)
- 📖 Docs: [Full Documentation](docs/)
