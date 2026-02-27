"""
Database Models
"""
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import uuid

db = SQLAlchemy()


class Device(db.Model):
    """Device model"""
    __tablename__ = 'devices'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    hostname = db.Column(db.String(255), nullable=False, unique=True)
    device_type = db.Column(db.String(50))  # laptop, desktop, server
    ip_address = db.Column(db.String(45))
    mac_address = db.Column(db.String(17))
    os_version = db.Column(db.String(100))
    status = db.Column(db.String(20), default='offline')  # online, offline, maintenance
    last_seen = db.Column(db.DateTime)
    last_gpupdate = db.Column(db.DateTime)
    pending_restart = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    storage_devices = db.relationship('Storage', back_populates='device', cascade='all, delete-orphan')
    tasks = db.relationship('Task', back_populates='device', cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'hostname': self.hostname,
            'device_type': self.device_type,
            'ip_address': self.ip_address,
            'mac_address': self.mac_address,
            'os_version': self.os_version,
            'status': self.status,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'last_gpupdate': self.last_gpupdate.isoformat() if self.last_gpupdate else None,
            'pending_restart': self.pending_restart,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }


class Storage(db.Model):
    """Storage device model - tracks external drives"""
    __tablename__ = 'storage'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id = db.Column(db.String(36), db.ForeignKey('devices.id'))
    
    # Persistent identifiers
    serial_number = db.Column(db.String(100), unique=True)  # Volume serial or disk serial
    disk_signature = db.Column(db.String(100))
    model = db.Column(db.String(200))
    
    # Current state
    drive_letter = db.Column(db.String(3))  # e.g., "D:"
    label = db.Column(db.String(255))
    total_size = db.Column(db.BigInteger)
    used_size = db.Column(db.BigInteger)
    storage_type = db.Column(db.String(20))  # hdd, ssd, usb
    
    # Folder tree (JSON)
    folder_tree = db.Column(db.JSON)
    
    # Status
    connected = db.Column(db.Boolean, default=False)
    last_seen = db.Column(db.DateTime)
    
    # Asset tag
    asset_tag = db.Column(db.String(50), unique=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    device = db.relationship('Device', back_populates='storage_devices')
    
    def to_dict(self):
        return {
            'id': self.id,
            'device_id': self.device_id,
            'serial_number': self.serial_number,
            'disk_signature': self.disk_signature,
            'model': self.model,
            'drive_letter': self.drive_letter,
            'label': self.label,
            'total_size': self.total_size,
            'used_size': self.used_size,
            'storage_type': self.storage_type,
            'folder_tree': self.folder_tree,
            'connected': self.connected,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'asset_tag': self.asset_tag,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }


class SyncJob(db.Model):
    """File synchronization job"""
    __tablename__ = 'sync_jobs'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(255), nullable=False)
    
    # Source configuration
    source_path = db.Column(db.String(500))
    source_device_id = db.Column(db.String(36))
    
    # Destinations (JSON array of device IDs and paths)
    destinations = db.Column(db.JSON)
    
    # Sync mode: push, sync, pull
    mode = db.Column(db.String(20), default='push')
    
    # Status
    enabled = db.Column(db.Boolean, default=True)
    last_sync = db.Column(db.DateTime)
    next_sync = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='pending')  # pending, running, completed, failed
    
    # Schedule (cron expression)
    schedule = db.Column(db.String(100))
    
    # Statistics
    files_synced = db.Column(db.Integer, default=0)
    bytes_synced = db.Column(db.BigInteger, default=0)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'source_path': self.source_path,
            'source_device_id': self.source_device_id,
            'destinations': self.destinations,
            'mode': self.mode,
            'enabled': self.enabled,
            'last_sync': self.last_sync.isoformat() if self.last_sync else None,
            'next_sync': self.next_sync.isoformat() if self.next_sync else None,
            'status': self.status,
            'schedule': self.schedule,
            'files_synced': self.files_synced,
            'bytes_synced': self.bytes_synced,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }


class Script(db.Model):
    """Script model"""
    __tablename__ = 'scripts'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    content = db.Column(db.Text, nullable=False)
    script_type = db.Column(db.String(20), default='powershell')  # powershell, batch, python
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    tasks = db.relationship('Task', back_populates='script', cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'content': self.content,
            'script_type': self.script_type,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }


class Task(db.Model):
    """Task model - associates scripts with devices"""
    __tablename__ = 'tasks'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id = db.Column(db.String(36), db.ForeignKey('devices.id'), nullable=False)
    script_id = db.Column(db.String(36), db.ForeignKey('scripts.id'), nullable=False)
    
    # Schedule (cron expression or 'manual')
    schedule = db.Column(db.String(100), default='manual')
    
    # Status
    enabled = db.Column(db.Boolean, default=True)
    last_run = db.Column(db.DateTime)
    last_status = db.Column(db.String(20))  # success, failed, running
    last_output = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    device = db.relationship('Device', back_populates='tasks')
    script = db.relationship('Script', back_populates='tasks')
    
    def to_dict(self):
        return {
            'id': self.id,
            'device_id': self.device_id,
            'script_id': self.script_id,
            'schedule': self.schedule,
            'enabled': self.enabled,
            'last_run': self.last_run.isoformat() if self.last_run else None,
            'last_status': self.last_status,
            'last_output': self.last_output,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }
