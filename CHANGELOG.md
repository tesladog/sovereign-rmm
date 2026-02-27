# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] - 2025-02-27

### Added
- Initial release
- Device management and tracking
- Persistent storage identification using volume serial numbers
- Automatic USB drive detection and scanning
- Folder tree scanning without reading file contents
- Group Policy monitoring (last gpupdate, pending restarts)
- File synchronization (Push, Sync, Pull modes)
- Asset tag generation (Standard, Compact, Mini sizes)
- Interactive MSI installer with Windows Server compatibility
- Docker deployment support
- WebSocket real-time updates
- RESTful API for all operations
- Script execution and task scheduling
- Windows service agent

### Fixed
- MSI build permission denied error for python.exe
- Container exit issues in Docker deployment
- Storage detection for drives without volume labels
- Permission handling for embedded Python runtime

### Security
- Added authentication token support
- Encrypted credential storage for sync hosts
- Rate limiting on API endpoints
- Input validation for all user-supplied data

## [Future Releases]

### Planned for 1.1.0
- Web UI (React frontend)
- Email notifications
- Backup scheduling
- Network discovery
- Active Directory integration
- Multi-server support
- Cloud sync integration (OneDrive, Dropbox)

### Planned for 1.2.0
- Mobile app (iOS/Android)
- Advanced reporting and analytics
- Automated patch management
- Remote desktop integration
- Custom plugin system
