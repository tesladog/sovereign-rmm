import asyncio, os, uuid, json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import redis.asyncio as aioredis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from models import Base, Device, Storage, Script, Task, InstalledSoftware, UpdatePackage, PendingUpdate, LockdownRule, Setting
from database import engine, AsyncSessionLocal, get_db
REDIS_URL = os.getenv("REDIS_URL", "")
AGENT_TOKEN = os.getenv("AGENT_TOKEN", "")
SERVER_IP = os.getenv("SERVER_IP", "localhost")
redis_pool = None
agent_connections = {}
dashboard_connections = {}
@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_pool
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    redis_pool = await aioredis.from_url(REDIS_URL, decode_responses=True)
    await seed_settings()
    asyncio.create_task(offline_detection_loop())
    yield
    await redis_pool.aclose()
    await engine.dispose()
app = FastAPI(title="Sovereign RMM", version="5.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
@app.get("/api/health")
async def health(): return {"status": "healthy", "version": "5.0.0", "timestamp": datetime.utcnow().isoformat()}
@app.get("/api/devices/")
async def get_devices(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Device))
    devices = result.scalars().all()
    return [{"id": d.id, "hostname": d.hostname, "device_type": d.device_type, "ip_address": d.ip_address, "os_version": d.os_version, "status": d.status, "last_seen": d.last_seen.isoformat() if d.last_seen else None, "locked_down": d.locked_down, "cpu_usage": d.cpu_usage, "ram_used": d.ram_used, "ram_total": d.ram_total} for d in devices]
@app.post("/api/devices/")
async def create_device(data: dict, db: AsyncSession = Depends(get_db)):
    device = Device(hostname=data.get("hostname"), device_type=data.get("device_type"), platform=data.get("platform"), ip_address=data.get("ip_address"), mac_address=data.get("mac_address"), os_version=data.get("os_version"))
    db.add(device)
    await db.commit()
    await db.refresh(device)
    return {"id": device.id, "hostname": device.hostname}
@app.post("/api/lockdown/device/{device_id}")
async def lockdown_device(device_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if device:
        device.locked_down = True
        await db.commit()
        if device_id in agent_connections: await agent_connections[device_id].send_json({"type": "lockdown_active"})
        return {"message": "Device locked down"}
    return {"error": "Device not found"}
@app.websocket("/ws/agent")
async def ws_agent(websocket: WebSocket):
    await websocket.accept()
    device_id = None
    try:
        data = await websocket.receive_json()
        if data.get("type") == "register":
            device_id = data.get("device_id")
            agent_connections[device_id] = websocket
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Device).where(Device.id == device_id))
                device = result.scalar_one_or_none()
                if device: device.status = "online"; device.last_seen = datetime.utcnow(); await db.commit()
            await websocket.send_json({"type": "connected", "device_id": device_id})
            while True:
                msg = await websocket.receive_json()
                if msg.get("type") == "heartbeat":
                    async with AsyncSessionLocal() as db:
                        result = await db.execute(select(Device).where(Device.id == device_id))
                        device = result.scalar_one_or_none()
                        if device: device.last_seen = datetime.utcnow(); device.cpu_usage = msg.get("cpu_usage"); device.ram_used = msg.get("ram_used"); await db.commit()
    except WebSocketDisconnect: pass
    finally:
        if device_id and device_id in agent_connections: del agent_connections[device_id]
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Device).where(Device.id == device_id))
            device = result.scalar_one_or_none()
            if device: device.status = "offline"; await db.commit()
async def seed_settings():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Setting).where(Setting.key == "server_ip"))
        if not result.scalar_one_or_none():
            db.add(Setting(key="server_ip", value=SERVER_IP, description="Server IP", category="network"))
            await db.commit()
async def offline_detection_loop():
    while True:
        try:
            async with AsyncSessionLocal() as db:
                threshold = datetime.utcnow() - timedelta(minutes=5)
                await db.execute(update(Device).where(Device.last_seen < threshold).values(status="offline"))
                await db.commit()
        except: pass
        await asyncio.sleep(60)
