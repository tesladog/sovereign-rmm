"""Enhanced Database Models with Update Management and Lockdown"""

from datetime import datetime
from sqlalchemy import Column, String, Integer, BigInteger, Boolean, DateTime, Text, JSON, ForeignKey, Float
from sqlalchemy.orm import relationship, declarative_base
import uuid

Base = declarative_base()


def generate_uuid():
    return str(uuid.uuid4())


class Device(Base):
    """Device model with enhanced statistics"""
    __tablename__ = "devices"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    hostname = Column(String(255), nullable=False, unique=True)
    device_type = Column(String(50))  # laptop, desktop, server
    platform = Column(String(20))  # windows, linux, android
    ip_address = Column(String(45))
    mac_address = Column(String(17))
    os_version = Column(String(100))
    os_build = Column(String(50))
    
    # Status
    status = Column(String(20), default="offline")  # online, offline, maintenance
    locked_down = Column(Boolean, default=False)  # Individual device lockdown
    last_seen = Column(DateTime)
    
    # Windows-specific
    last_gpupdate = Column(DateTime)
    pending_restart = Column(Boolean, default=False)
    
    # Hardware stats
    cpu_model = Column(String(200))
    cpu_cores = Column(Integer)
    cpu_usage = Column(Float)  # Current percentage
    ram_total = Column(BigInteger)
    ram_used = Column(BigInteger)
    disk_total = Column(BigInteger)
    disk_used = Column(BigInteger)
    
    # Network stats
    network_sent = Column(BigInteger)  # Bytes sent
    network_recv = Column(BigInteger)  # Bytes received
    
    # Agent info
    agent_version = Column(String(20))
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    storage_devices = relationship("Storage", back_populates="device", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="device", cascade="all, delete-orphan")
    software = relationship("InstalledSoftware", back_populates="device", cascade="all, delete-orphan")
    processes = relationship("RunningProcess", back_populates="device", cascade="all, delete-orphan")
    updates = relationship("PendingUpdate", back_populates="device", cascade="all, delete-orphan")


class Storage(Base):
    """Storage device model"""
    __tablename__ = "storage"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    device_id = Column(String(36), ForeignKey("devices.id"))
    
    serial_number = Column(String(100), unique=True)
    disk_signature = Column(String(100))
    model = Column(String(200))
    drive_letter = Column(String(3))
    label = Column(String(255))
    total_size = Column(BigInteger)
    used_size = Column(BigInteger)
    storage_type = Column(String(20))  # hdd, ssd, usb
    folder_tree = Column(JSON)
    connected = Column(Boolean, default=False)
    last_seen = Column(DateTime)
    asset_tag = Column(String(50), unique=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    device = relationship("Device", back_populates="storage_devices")


class Script(Base):
    """Script model with platform support"""
    __tablename__ = "scripts"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    content = Column(Text, nullable=False)
    script_type = Column(String(20), default="powershell")  # powershell, bash, python
    platform = Column(String(20))  # windows, linux, android, all
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    tasks = relationship("Task", back_populates="script", cascade="all, delete-orphan")


class Task(Base):
    """Task model"""
    __tablename__ = "tasks"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    device_id = Column(String(36), ForeignKey("devices.id"), nullable=False)
    script_id = Column(String(36), ForeignKey("scripts.id"), nullable=False)
    schedule = Column(String(100), default="manual")
    enabled = Column(Boolean, default=True)
    last_run = Column(DateTime)
    last_status = Column(String(20))
    last_output = Column(Text)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    device = relationship("Device", back_populates="tasks")
    script = relationship("Script", back_populates="tasks")


class TaskResult(Base):
    """Task execution result"""
    __tablename__ = "task_results"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=False)
    status = Column(String(20))
    output = Column(Text)
    error = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class SyncJob(Base):
    """File synchronization job"""
    __tablename__ = "sync_jobs"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    source_path = Column(String(500))
    source_device_id = Column(String(36))
    destinations = Column(JSON)
    mode = Column(String(20), default="push")
    enabled = Column(Boolean, default=True)
    last_sync = Column(DateTime)
    next_sync = Column(DateTime)
    status = Column(String(20), default="pending")
    schedule = Column(String(100))
    files_synced = Column(Integer, default=0)
    bytes_synced = Column(BigInteger, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class InstalledSoftware(Base):
    """Installed software inventory"""
    __tablename__ = "installed_software"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    device_id = Column(String(36), ForeignKey("devices.id"), nullable=False)
    name = Column(String(255))
    version = Column(String(100))
    publisher = Column(String(255))
    install_date = Column(DateTime)
    install_location = Column(String(500))
    size = Column(BigInteger)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    device = relationship("Device", back_populates="software")


class RunningProcess(Base):
    """Running processes"""
    __tablename__ = "running_processes"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    device_id = Column(String(36), ForeignKey("devices.id"), nullable=False)
    name = Column(String(255))
    pid = Column(Integer)
    cpu_percent = Column(Float)
    memory_mb = Column(Float)
    username = Column(String(100))
    status = Column(String(50))
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    device = relationship("Device", back_populates="processes")


class UpdatePackage(Base):
    """Available update packages (stored on server)"""
    __tablename__ = "update_packages"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    version = Column(String(100))
    platform = Column(String(20))  # windows, linux, android
    package_type = Column(String(50))  # windows_update, apt_package, apk_file, msi
    description = Column(Text)
    
    # File info
    file_path = Column(String(500))  # Path in update_cache volume
    file_size = Column(BigInteger)
    file_hash = Column(String(64))  # SHA256
    
    # Metadata
    severity = Column(String(20))  # critical, important, moderate, low
    kb_number = Column(String(20))  # For Windows updates
    cve_numbers = Column(JSON)  # Array of CVE IDs
    
    # Status
    approved = Column(Boolean, default=False)
    auto_approve = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    pending_installs = relationship("PendingUpdate", back_populates="package", cascade="all, delete-orphan")


class PendingUpdate(Base):
    """Updates pending installation on devices"""
    __tablename__ = "pending_updates"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    device_id = Column(String(36), ForeignKey("devices.id"), nullable=False)
    package_id = Column(String(36), ForeignKey("update_packages.id"), nullable=False)
    
    status = Column(String(20), default="pending")  # pending, downloading, installing, installed, failed, declined
    progress = Column(Integer, default=0)  # 0-100
    error_message = Column(Text)
    
    scheduled_install = Column(DateTime)
    installed_at = Column(DateTime)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    device = relationship("Device", back_populates="updates")
    package = relationship("UpdatePackage", back_populates="pending_installs")


class LockdownRule(Base):
    """Lockdown rules for devices"""
    __tablename__ = "lockdown_rules"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    
    # Rule type
    rule_type = Column(String(50))  # block_process, block_network, block_usb, restrict_user
    
    # Rule configuration (JSON)
    config = Column(JSON)
    
    # Scope
    global_rule = Column(Boolean, default=False)  # Apply to all devices
    device_ids = Column(JSON)  # Array of specific device IDs
    
    enabled = Column(Boolean, default=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LogEntry(Base):
    """Log entry"""
    __tablename__ = "log_entries"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    device_id = Column(String(36), ForeignKey("devices.id"))
    level = Column(String(20))
    message = Column(Text)
    details = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)


class Setting(Base):
    """Application settings"""
    __tablename__ = "settings"
    
    key = Column(String(100), primary_key=True)
    value = Column(Text)
    description = Column(String(255))
    category = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
