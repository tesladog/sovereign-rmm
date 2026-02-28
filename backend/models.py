from datetime import datetime
from sqlalchemy import Column, String, Integer, BigInteger, Boolean, DateTime, Text, JSON, ForeignKey, Float
from sqlalchemy.orm import relationship, declarative_base
import uuid
Base = declarative_base()
def gen_uuid(): return str(uuid.uuid4())
class Device(Base):
    __tablename__ = "devices"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    hostname = Column(String(255), nullable=False, unique=True)
    device_type = Column(String(50)); platform = Column(String(20)); ip_address = Column(String(45))
    mac_address = Column(String(17)); os_version = Column(String(100)); status = Column(String(20), default="offline")
    locked_down = Column(Boolean, default=False); last_seen = Column(DateTime); last_gpupdate = Column(DateTime)
    pending_restart = Column(Boolean, default=False); cpu_usage = Column(Float); ram_total = Column(BigInteger)
    ram_used = Column(BigInteger); disk_total = Column(BigInteger); disk_used = Column(BigInteger)
    agent_version = Column(String(20)); created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
class Setting(Base):
    __tablename__ = "settings"
    key = Column(String(100), primary_key=True); value = Column(Text); description = Column(String(255))
    category = Column(String(50)); updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
