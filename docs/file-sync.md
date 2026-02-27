# File Sync Guide

## Overview

The file synchronization system allows you to distribute files across multiple devices, similar to Syncthing. It supports three modes:
- **Push**: One-way from server to devices
- **Sync**: Two-way synchronization between all devices
- **Pull**: Devices pull updates from a source

## Sync Modes

### Push Mode

Server has the file, pushes to selected devices.

**Use cases:**
- Deploying configuration files
- Distributing software updates
- Pushing scripts to devices

**Example:**
```python
# Upload file and push to devices
import requests

with open('config.ini', 'rb') as f:
    response = requests.post(
        'http://server:5000/api/sync/upload',
        files={'file': f},
        data={'targets': ['device-1-uuid', 'device-2-uuid']}
    )
```

**Via UI:**
1. Go to Sync tab
2. Click "Upload & Push"
3. Select file
4. Choose target devices
5. Click "Push"

### Sync Mode (Bidirectional)

All devices keep the same version of files.

**Use cases:**
- Shared project folders
- Team documents
- Collaborative work

**Example:**
```python
import requests

response = requests.post(
    'http://server:5000/api/sync/jobs',
    json={
        'name': 'Project Files',
        'source_path': 'C:\\Projects\\Active',
        'destinations': [
            {'device_id': 'device-1', 'path': 'D:\\Projects\\Active'},
            {'device_id': 'device-2', 'path': 'C:\\Work\\Projects'}
        ],
        'mode': 'sync',
        'schedule': '*/30 * * * *'  # Every 30 minutes
    }
)
```

**Conflict Resolution:**
- Last modified wins
- Conflicted files saved as `.conflict`
- Manual resolution required for conflicts

### Pull Mode

Devices pull files from a central source.

**Use cases:**
- Backup collection
- Log aggregation
- Report gathering

**Example:**
```python
response = requests.post(
    'http://server:5000/api/sync/jobs',
    json={
        'name': 'Daily Logs',
        'source_path': 'C:\\Logs',
        'source_device_id': 'server-device-id',
        'destinations': [
            {'device_id': 'backup-server', 'path': '/backups/logs'}
        ],
        'mode': 'pull',
        'schedule': '0 2 * * *'  # Daily at 2 AM
    }
)
```

## Setting Up Sync Jobs

### Via Web UI

```
Sync Tab → Create Job

┌─────────────────────────────────────────────────┐
│ Create Sync Job                                  │
├─────────────────────────────────────────────────┤
│                                                  │
│ Job Name: *                                      │
│ ┌─────────────────────────────────────────────┐│
│ │ Marketing Materials                          ││
│ └─────────────────────────────────────────────┘│
│                                                  │
│ Mode: * [ Push ▼ ]                              │
│                                                  │
│ Source:                                          │
│ ┌─────────────────────────────────────────────┐│
│ │ \\server\share\marketing                     ││
│ └─────────────────────────────────────────────┘│
│                                                  │
│ Destinations:                                    │
│ ┌─────────────────────────────────────────────┐│
│ │ ☑ LAPTOP-001  → C:\Marketing                 ││
│ │ ☑ LAPTOP-002  → C:\Marketing                 ││
│ │ ☐ DESKTOP-01  → D:\Work\Marketing            ││
│ └─────────────────────────────────────────────┘│
│                                                  │
│ Schedule:                                        │
│ ( ) Manual                                       │
│ (•) Scheduled: [Every hour ▼]                   │
│                                                  │
│          [Cancel]  [Create Job]                 │
└─────────────────────────────────────────────────┘
```

### Via API

**Create Job:**
```http
POST /api/sync/jobs
Content-Type: application/json

{
  "name": "Marketing Materials",
  "source_path": "\\\\server\\share\\marketing",
  "destinations": [
    {
      "device_id": "laptop-001-uuid",
      "path": "C:\\Marketing"
    },
    {
      "device_id": "laptop-002-uuid",
      "path": "C:\\Marketing"
    }
  ],
  "mode": "push",
  "schedule": "0 * * * *",
  "enabled": true
}
```

**List Jobs:**
```http
GET /api/sync/jobs
```

**Get Job Status:**
```http
GET /api/sync/jobs/{job_id}
```

**Trigger Manual Sync:**
```http
POST /api/sync/jobs/{job_id}/run
```

## Scheduling

### Cron Expressions

```
# Every hour
0 * * * *

# Every 30 minutes
*/30 * * * *

# Daily at 2 AM
0 2 * * *

# Weekdays at 9 AM
0 9 * * 1-5

# Every 6 hours
0 */6 * * *
```

### Pre-defined Schedules

- `manual` - Only run when triggered
- `hourly` - Every hour
- `daily` - Daily at midnight
- `weekly` - Weekly on Sunday
- `monthly` - First of the month

## Host Path Configuration

### Setting Up a Sync Host

A sync host is a central location (server or NAS) where files are stored.

**Example: NAS as Sync Host**

```python
# Configure NAS as sync source
response = requests.post(
    'http://server:5000/api/sync/hosts',
    json={
        'name': 'Main NAS',
        'path': '\\\\nas.local\\sync',
        'type': 'smb',
        'credentials': {
            'username': 'syncuser',
            'password': 'encrypted-password'
        }
    }
)

# Use NAS in sync job
response = requests.post(
    'http://server:5000/api/sync/jobs',
    json={
        'name': 'NAS Documents',
        'source_host': 'nas-uuid',
        'source_path': 'Documents',
        'destinations': [
            {'device_id': 'laptop-1', 'path': 'C:\\Documents'}
        ],
        'mode': 'sync'
    }
)
```

### Server Upload Directory

Upload files to server, then distribute:

```python
# Upload to server
with open('file.zip', 'rb') as f:
    response = requests.post(
        'http://server:5000/api/sync/upload',
        files={'file': f}
    )
    
file_id = response.json()['file_id']

# Create distribution job
response = requests.post(
    'http://server:5000/api/sync/jobs',
    json={
        'name': 'Distribute Update',
        'source_file_id': file_id,
        'destinations': [
            {'device_id': 'all-laptops', 'path': 'C:\\Updates'}
        ],
        'mode': 'push'
    }
)
```

## Monitoring Sync Status

### Real-time Updates via WebSocket

```javascript
const socket = io('http://server:5000');

socket.on('sync_job_updated', (data) => {
  console.log(`Job ${data.job_id}: ${data.status}`);
  console.log(`Files: ${data.files_synced}, Bytes: ${data.bytes_synced}`);
});

socket.on('sync_progress', (data) => {
  console.log(`Progress: ${data.percent}%`);
});
```

### Status Dashboard

```
┌─────────────────────────────────────────────────────────┐
│ Sync Jobs                                               │
├─────────────────────────────────────────────────────────┤
│                                                          │
│ Marketing Materials                    [Running] 45%    │
│ ├─ LAPTOP-001                          ✓ Complete       │
│ └─ LAPTOP-002                          ⟳ Syncing...     │
│                                                          │
│ Project Files                          [Idle]           │
│ ├─ DESKTOP-01                          ✓ Up to date     │
│ ├─ LAPTOP-003                          ⚠ Conflict       │
│ └─ LAPTOP-004                          ✗ Failed         │
│   Next sync: in 15 minutes                              │
│                                                          │
│ Daily Logs                             [Scheduled]      │
│ └─ All devices                         ⏰ Tonight 2 AM  │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

## Bandwidth Control

### Limit Sync Speed

```python
# Throttle sync to 5 MB/s
response = requests.put(
    'http://server:5000/api/sync/jobs/{job_id}/settings',
    json={
        'max_bandwidth': 5 * 1024 * 1024,  # 5 MB/s in bytes
        'priority': 'low'
    }
)
```

### Schedule for Off-Peak Hours

```python
# Large transfers only at night
response = requests.post(
    'http://server:5000/api/sync/jobs',
    json={
        'name': 'Large Backups',
        'source_path': 'C:\\Backups',
        'destinations': [...],
        'mode': 'push',
        'schedule': '0 2 * * *',  # 2 AM
        'max_bandwidth': None,  # No limit during off-peak
        'allowed_hours': '22:00-08:00'  # Only 10 PM - 8 AM
    }
)
```

## Exclusions and Filters

### Exclude Files/Folders

```python
response = requests.post(
    'http://server:5000/api/sync/jobs',
    json={
        'name': 'Code Sync',
        'source_path': 'C:\\Projects',
        'destinations': [...],
        'mode': 'sync',
        'exclude_patterns': [
            'node_modules/',
            '*.log',
            '.git/',
            '__pycache__/',
            '*.tmp'
        ]
    }
)
```

### Include Only Specific Files

```python
response = requests.post(
    'http://server:5000/api/sync/jobs',
    json={
        'name': 'Documents Only',
        'source_path': 'C:\\Data',
        'destinations': [...],
        'mode': 'sync',
        'include_patterns': [
            '*.docx',
            '*.pdf',
            '*.xlsx'
        ]
    }
)
```

## Troubleshooting

### Sync Not Starting

**Check job status:**
```bash
curl http://server:5000/api/sync/jobs/{job_id}
```

**Check device connectivity:**
```bash
curl http://server:5000/api/devices/{device_id}
# Verify status is 'online'
```

**Trigger manual sync:**
```bash
curl -X POST http://server:5000/api/sync/jobs/{job_id}/run
```

### Conflicts

When the same file is modified on multiple devices:

```
conflict_file.txt
conflict_file.txt.conflict.laptop-001.20250227-143022
conflict_file.txt.conflict.laptop-002.20250227-143045
```

**Resolve manually:**
1. Review all conflict versions
2. Choose the correct version
3. Delete conflict files
4. Resume sync

**Or use auto-resolve:**
```python
response = requests.put(
    'http://server:5000/api/sync/jobs/{job_id}/settings',
    json={
        'conflict_resolution': 'latest',  # or 'source', 'manual'
    }
)
```

### Slow Sync Performance

**Reduce file count:**
```python
# Sync archives instead of many small files
# Use exclusions to skip unnecessary files
```

**Increase sync threads:**
```python
response = requests.put(
    'http://server:5000/api/sync/settings',
    json={
        'max_concurrent_transfers': 5,  # Increase from 3
        'chunk_size': 1024 * 1024  # 1 MB chunks
    }
)
```

## Best Practices

1. **Use Specific Paths**: Don't sync entire drives
2. **Exclude Temp Files**: Add `.tmp`, `.log`, etc. to exclusions
3. **Test First**: Try with small folders before large syncs
4. **Monitor Initially**: Watch first few syncs for issues
5. **Schedule Wisely**: Large transfers during off-peak hours
6. **Regular Cleanup**: Remove completed one-time sync jobs

## Next Steps

- [Storage Management](storage.md)
- [API Reference](api.md)
- [Troubleshooting](troubleshooting.md)
