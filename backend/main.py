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
