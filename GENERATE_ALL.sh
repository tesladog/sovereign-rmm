#!/bin/bash
# Complete Database Models
cat > backend/models.py << 'PYEOF'
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
PYEOF

# Database Connection
cat > backend/database.py << 'PYEOF'
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True, pool_size=10, max_overflow=20)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
async def get_db():
    async with AsyncSessionLocal() as session:
        try: yield session
        finally: await session.close()
PYEOF

# Main FastAPI App
cat > backend/main.py << 'PYEOF'
import asyncio, os, uuid
from contextlib import asynccontextmanager
from datetime import datetime
import redis.asyncio as aioredis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from models import Base, Device, Setting
from database import engine, AsyncSessionLocal
REDIS_URL = os.getenv("REDIS_URL", "")
AGENT_TOKEN = os.getenv("AGENT_TOKEN", "")
redis_pool = None
agent_connections = {}
@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_pool
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    redis_pool = await aioredis.from_url(REDIS_URL, decode_responses=True)
    yield
    await redis_pool.aclose()
    await engine.dispose()
app = FastAPI(title="Sovereign RMM", version="5.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
from routes import devices
app.include_router(devices.router, prefix="/api/devices", tags=["Devices"])
@app.get("/api/health")
async def health(): return {"status": "healthy", "version": "5.0.0"}
@app.websocket("/ws/agent")
async def ws_agent(websocket: WebSocket):
    await websocket.accept()
    device_id = None
    try:
        data = await websocket.receive_json()
        if data.get("type") == "register":
            device_id = data.get("device_id")
            agent_connections[device_id] = websocket
            await websocket.send_json({"type": "connected"})
            while True: msg = await websocket.receive_json()
    except WebSocketDisconnect: pass
    finally:
        if device_id in agent_connections: del agent_connections[device_id]
PYEOF

# Routes Init
touch backend/routes/__init__.py

# Devices Route
cat > backend/routes/devices.py << 'PYEOF'
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import sys
sys.path.append('..')
from database import get_db
from models import Device
router = APIRouter()
class DeviceResponse(BaseModel):
    id: str; hostname: str; device_type: Optional[str]; ip_address: Optional[str]
    os_version: Optional[str]; status: str; last_seen: Optional[datetime]
    class Config: from_attributes = True
@router.get("/", response_model=List[DeviceResponse])
async def get_devices(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Device))
    return result.scalars().all()
PYEOF

echo "Backend complete"

# Frontend Dockerfile
cat > frontend/Dockerfile << 'EOF'
FROM nginx:alpine
COPY frontend/nginx.conf /etc/nginx/nginx.conf
COPY frontend/index.html /usr/share/nginx/html/
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
EOF

# Nginx Config
cat > frontend/nginx.conf << 'EOF'
events { worker_connections 1024; }
http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    sendfile on;
    keepalive_timeout 65;
    server {
        listen 80;
        server_name _;
        root /usr/share/nginx/html;
        index index.html;
        location / { try_files $uri $uri/ /index.html; }
        location /api/ {
            proxy_pass http://backend:8000;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
        }
        location /ws/ {
            proxy_pass http://backend:8000;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
        }
    }
}
EOF

echo "Frontend complete"

# Agents
echo 'print("Windows Agent")' > agent-windows/windows_agent.py
echo 'print("Linux Agent")' > agent-linux/linux_agent.py
echo 'print("Android Agent")' > agent-android/android_agent.py

echo "✓ ALL FILES GENERATED"
