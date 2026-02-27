# Storage Management Guide

## Overview

The storage management system tracks external drives (HDDs, SSDs, USBs) using persistent identifiers rather than drive letters. This allows the system to recognize drives even when their drive letter changes.

## How It Works

### Persistent Identification

Drives are identified by:
1. **Volume Serial Number** (Primary) - Unique to each formatted volume
2. **Disk Signature** (Secondary) - Hardware identifier
3. **Model and Serial Number** (Tertiary) - Physical device identifiers

This means you can:
- Wipe a drive and it will still be recognized
- Move a drive to a different port/computer
- Change the drive letter
- The system will still track it

### Folder Tree Scanning

When a drive is detected, the system:
1. Scans the folder structure (not file contents)
2. Stores the tree up to 3 levels deep (configurable)
3. Updates the tree on each reconnection
4. Allows you to see which drive has which folders without plugging it in

## Storage Tab UI

### Overview Screen

```
┌─────────────────────────────────────────────────────────┐
│ Storage Devices                               [Scan All]│
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────┐                                       │
│  │   SS-2502-   │  Samsung 870 EVO 500GB                │
│  │     0042     │  Connected: Yes                       │
│  │   [QR Code]  │  Drive: E:\                           │
│  └──────────────┘  Used: 234 GB / 500 GB                │
│                     Last Seen: 2 minutes ago            │
│                     [View Tree] [Generate Tag] [Eject]  │
│                                                          │
│  ┌──────────────┐                                       │
│  │   HD-2502-   │  WD Blue 1TB                          │
│  │     0123     │  Connected: No                        │
│  │   [QR Code]  │  Drive: --                            │
│  └──────────────┘  Used: 789 GB / 1000 GB               │
│                     Last Seen: 2 days ago               │
│                     [View Tree] [Generate Tag]          │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### Folder Tree View

```
Samsung 870 EVO (E:\) - SS-2502-0042
├── Projects
│   ├── Web
│   ├── Mobile
│   └── Desktop
├── Backups
│   ├── 2025-01
│   └── 2025-02
├── Documents
│   ├── Work
│   └── Personal
└── Media
    ├── Photos
    └── Videos
```

## Automatic Detection

### USB Drive Insertion

When you plug in a USB drive:
1. System detects insertion within 2 seconds
2. Automatically scans the drive
3. Checks if it's a known drive (by serial number)
4. Updates or creates storage entry
5. Scans folder tree
6. Updates UI in real-time via WebSocket
7. Generates asset tag if new drive

### Configuration

```json
// agent_config.json
{
  "storage": {
    "auto_scan": true,
    "scan_depth": 3,
    "scan_on_insert": true,
    "update_tree_on_reconnect": true
  }
}
```

## Asset Tags

### Tag Types

#### Compact Tags (HDDs/SSDs)
- Size: 100mm x 40mm
- Includes: QR code + Asset ID + Type indicator
- Printable on standard label paper
- High contrast for readability

#### Mini Tags (M.2 SSDs)
- Size: 75mm x 30mm
- Minimal design
- QR code + ID only

#### Standard Tags (Devices)
- Size: 200mm x 80mm
- Includes: QR code + Asset ID + Hostname + Device type

### Generating Tags

Via UI:
```
1. Click on storage device
2. Click "Generate Tag"
3. Choose tag size (Compact, Mini, Standard)
4. Download PNG or PDF
5. Print on label paper
```

Via API:
```python
import requests

response = requests.post(
    'http://server:5000/api/storage/generate-tag',
    json={
        'storage_id': 'uuid-here',
        'tag_type': 'compact'  # or 'mini', 'standard'
    }
)

with open('tag.png', 'wb') as f:
    f.write(response.content)
```

Via CLI:
```bash
python src/utils/asset_tags.py --generate \
    --id SS-2502-0042 \
    --type ssd \
    --size compact \
    --output tag.png
```

### Batch Printing

Generate a sheet with multiple tags:

```python
from src.utils.asset_tags import AssetTagGenerator

generator = AssetTagGenerator()

tags = []
for i in range(1, 21):  # 20 tags
    tag_id = f"SS-2502-{i:04d}"
    tag = generator.create_compact_tag(tag_id, "ssd")
    tags.append(tag)

# Create 4x5 grid
sheet = generator.generate_sheet(tags, columns=4)
sheet.save("tag_sheet.png", dpi=300)
```

## Manual Operations

### Manually Scan a Drive

```powershell
# Via PowerShell
Invoke-RestMethod -Method Post -Uri "http://server:5000/api/storage/scan" `
    -Body (@{drive_letter="E"; device_id="device-uuid"} | ConvertTo-Json) `
    -ContentType "application/json"
```

```bash
# Via curl
curl -X POST http://server:5000/api/storage/scan \
    -H "Content-Type: application/json" \
    -d '{"drive_letter":"E","device_id":"device-uuid"}'
```

### Update Folder Tree

```python
import requests

response = requests.post(
    'http://server:5000/api/storage/update-tree',
    json={'storage_id': 'uuid-here'}
)
```

### Mark Drive as Disconnected

```python
import requests

response = requests.post(
    'http://server:5000/api/storage/disconnect',
    json={'serial_number': 'ABCD1234'}
)
```

## Search and Filter

### Finding a Drive

**By folder contents:**
```
"Where is my drive that has Projects/Web folder?"

1. Go to Storage tab
2. Click "Search Tree"
3. Enter: "Projects/Web"
4. System shows all drives with this path
```

**By asset tag:**
```
Scan QR code or enter tag ID
```

**By model:**
```
Filter by manufacturer/model
```

## Best Practices

### 1. Label Immediately

When you add a new drive:
1. System generates asset tag
2. Print and apply tag immediately
3. Record in physical inventory log

### 2. Regular Scans

Set up periodic scans:
```json
// In server config
{
  "storage_scan_schedule": "0 */6 * * *"  // Every 6 hours
}
```

### 3. Backup Tree Data

The folder tree data is valuable:
```bash
# Backup database
docker-compose exec server \
    python -c "from models import db; db.backup('backup.db')"
```

### 4. Standardize Naming

Use consistent folder structures:
```
Recommended structure:
├── Backups
│   └── YYYY-MM
├── Projects
│   ├── Active
│   └── Archive
├── Documents
└── Media
```

## Troubleshooting

### Drive Not Detected

**Check USB monitoring:**
```powershell
# View agent logs
Get-Content "C:\Program Files\DeviceManagement\agent.log" | Select-String "USB"
```

**Manually trigger scan:**
```powershell
Invoke-RestMethod -Method Post -Uri "http://server:5000/api/storage/scan" `
    -Body (@{drive_letter="E"} | ConvertTo-Json) `
    -ContentType "application/json"
```

### Wrong Drive Identified

This can happen if:
1. Drive was reformatted (new volume serial)
2. Cloned drives (same serial)

**Solution:**
```python
# Update drive identification
import requests

requests.put(
    'http://server:5000/api/storage/update-id',
    json={
        'old_serial': 'ABC123',
        'new_serial': 'XYZ789'
    }
)
```

### Slow Folder Tree Scan

**Reduce scan depth:**
```json
// agent_config.json
{
  "storage_scan_depth": 2  // Reduce from 3
}
```

**Exclude folders:**
```json
{
  "storage_scan_exclude": [
    "$RECYCLE.BIN",
    "System Volume Information",
    "node_modules"
  ]
}
```

### Asset Tag Not Printing

**Check DPI:**
```python
# Generate high-DPI image
tag.save("tag.png", dpi=(600, 600))  # 600 DPI for quality
```

**Test print:**
1. Print one tag first
2. Measure actual size
3. Adjust if needed

## API Reference

### Scan Drive
```http
POST /api/storage/scan
Content-Type: application/json

{
  "drive_letter": "E",
  "device_id": "optional-uuid"
}
```

### Get All Storage
```http
GET /api/storage
```

### Get Storage by ID
```http
GET /api/storage/{storage_id}
```

### Search Folder Tree
```http
POST /api/storage/search
Content-Type: application/json

{
  "query": "Projects/Web",
  "connected_only": false
}
```

### Generate Tag
```http
POST /api/storage/generate-tag
Content-Type: application/json

{
  "storage_id": "uuid",
  "tag_type": "compact",
  "format": "png"
}
```

## Next Steps

- [File Sync Setup](file-sync.md) - Setup file synchronization
- [API Documentation](api.md) - Full API reference
- [Asset Tags](asset-tags.md) - Detailed tag guide
