from datetime import datetime
from sqlalchemy import Column, String, Integer, BigInteger, Boolean, DateTime, Text, JSON, ForeignKey, Float
from sqlalchemy.orm import relationship, declarative_base
import uuid

Base = declarative_base()

def gen_uuid():
    return str(uuid.uuid4())

class Device(Base):
    __tablename__ = "devices"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    hostname = Column(String(255), nullable=False, unique=True)
    device_type = Column(String(50))
    platform = Column(String(20))
    ip_address = Column(String(45))
    mac_address = Column(String(17))
    os_version = Column(String(100))
    status = Column(String(20), default="offline")
    locked_down = Column(Boolean, default=False)
    last_seen = Column(DateTime)
    last_gpupdate = Column(DateTime)
    pending_restart = Column(Boolean, default=False)
    cpu_usage = Column(Float)
    ram_total = Column(BigInteger)
    ram_used = Column(BigInteger)
    disk_total = Column(BigInteger)
    disk_used = Column(BigInteger)
    agent_version = Column(String(20))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    storage_devices = relationship("Storage", back_populates="device", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="device", cascade="all, delete-orphan")

class Storage(Base):
    __tablename__ = "storage"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    device_id = Column(String(36), ForeignKey("devices.id"))
    serial_number = Column(String(100), unique=True)
    model = Column(String(200))
    drive_letter = Column(String(3))
    label = Column(String(255))
    total_size = Column(BigInteger)
    used_size = Column(BigInteger)
    storage_type = Column(String(20))
    folder_tree = Column(JSON)
    connected = Column(Boolean, default=False)
    last_seen = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    device = relationship("Device", back_populates="storage_devices")

class Script(Base):
    __tablename__ = "scripts"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    content = Column(Text, nullable=False)
    script_type = Column(String(20), default="powershell")
    platform = Column(String(20))
    created_at = Column(DateTime, default=datetime.utcnow)
    tasks = relationship("Task", back_populates="script", cascade="all, delete-orphan")

class Task(Base):
    __tablename__ = "tasks"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    device_id = Column(String(36), ForeignKey("devices.id"), nullable=False)
    script_id = Column(String(36), ForeignKey("scripts.id"), nullable=False)
    schedule = Column(String(100), default="manual")
    enabled = Column(Boolean, default=True)
    last_run = Column(DateTime)
    last_status = Column(String(20))
    last_output = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    device = relationship("Device", back_populates="tasks")
    script = relationship("Script", back_populates="tasks")

class Setting(Base):
    __tablename__ = "settings"
    key = Column(String(100), primary_key=True)
    value = Column(Text)
    description = Column(String(255))
    category = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
