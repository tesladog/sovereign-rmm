"""SOVEREIGN RMM v2 — Main Application"""

import asyncio, json, os, uuid
from contextlib import asynccontextmanager
from datetime import datetime

import redis.asyncio as aioredis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, update

from models import Base, Device, Task, TaskResult, LogEntry, Policy, Setting, AgentVersion
from database import engine, AsyncSessionLocal, get_db

DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL    = os.getenv("REDIS_URL")
AGENT_TOKEN  = os.getenv("AGENT_TOKEN", "")

redis_pool = None

agent_connections: dict[str, WebSocket] = {}
dashboard_connections: dict[str, WebSocket] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_pool
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    redis_pool = await aioredis.from_url(REDIS_URL, decode_responses=True)
    await seed_default_settings()
    asyncio.create_task(listen_for_push_commands())
    asyncio.create_task(task_scheduler_loop())
    yield
    await redis_pool.aclose()
    await engine.dispose()


app = FastAPI(title="Sovereign RMM v2", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

# ── LOCKDOWN MIDDLEWARE ───────────────────────────────────────
@app.middleware("http")
async def lockdown_middleware(request: Request, call_next):
    if request.url.path == "/api/auth/login" and request.method == "POST":
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Setting).where(Setting.key == "lockdown_enabled"))
            s = result.scalar_one_or_none()
            if s and s.value == "true":
                return JSONResponse({"detail": "LOCKDOWN_ACTIVE"}, status_code=423)
    return await call_next(request)

# ── ROUTES ────────────────────────────────────────────────────
from routes import auth, devices, tasks, policies, dashboard, settings, scripts, inventory, builds, alerts
from routes import lockdown, wol, email_svc, hardware, backup

app.include_router(auth.router,      prefix="/api/auth",      tags=["Auth"])
app.include_router(devices.router,   prefix="/api/devices",   tags=["Devices"])
app.include_router(tasks.router,     prefix="/api/tasks",     tags=["Tasks"])
app.include_router(policies.router,  prefix="/api/policies",  tags=["Policies"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(settings.router,  prefix="/api/settings",  tags=["Settings"])
app.include_router(scripts.router,   prefix="/api/scripts",   tags=["Scripts"])
app.include_router(inventory.router, prefix="/api/inventory", tags=["Inventory"])
app.include_router(builds.router,    prefix="/api/builds",    tags=["Builds"])
app.include_router(alerts.router,    prefix="/api/alerts",    tags=["Alerts"])
app.include_router(lockdown.router,  prefix="/api/lockdown",  tags=["Lockdown"])
app.include_router(wol.router,       prefix="/api/wol",       tags=["WoL"])
app.include_router(email_svc.router, prefix="/api/email",     tags=["Email"])
app.include_router(hardware.router,  prefix="/api/hardware",  tags=["Hardware"])
app.include_router(backup.router,    prefix="/api/backup",    tags=["Backup"])


# ── SEED SETTINGS ────────────────────────────────────────────
async def seed_default_settings():
    defaults = [
        ("server_ip",         os.getenv("SERVER_IP", "192.168.5.199"), "Server Local IP",    "network"),
        ("vpn_ip",            "100.125.120.81",                         "Server VPN IP",      "network"),
        ("backend_port",      os.getenv("BACKEND_PORT", "8000"),        "Backend Port",       "network"),
        ("agent_token",       AGENT_TOKEN,                               "Agent Token",        "security"),
        ("admin_username",    os.getenv("ADMIN_USERNAME", "admin"),      "Admin Username",     "auth"),
        ("smtp_host",         "",                                        "SMTP Host",          "email"),
        ("smtp_port",         "587",                                     "SMTP Port",          "email"),
        ("smtp_user",         "",                                        "SMTP User",          "email"),
        ("smtp_pass",         "",                                        "SMTP Password",      "email"),
        ("alert_email",       "",                                        "Alert Email",        "email"),
        ("lockdown_enabled",  "false",                                   "Lockdown Mode",      "security"),
    ]
    async with AsyncSessionLocal() as db:
        for key, value, label, category in defaults:
            result = await db.execute(select(Setting).where(Setting.key == key))
            if not result.scalar_one_or_none():
                db.add(Setting(key=key, value=value, label=label, category=category))
        await db.commit()


# ── REDIS PUSH LISTENER ───────────────────────────────────────
async def listen_for_push_commands():
    global redis_pool
    while True:
        try:
            pubsub = redis_pool.pubsub()
            await pubsub.subscribe("push_commands")
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        cmd = json.loads(message["data"])
                        device_id = cmd.get("device_id")
                        if device_id and device_id in agent_connections:
                            ws = agent_connections[device_id]
                            await ws.send_json(cmd)
                        elif not device_id:
                            for ws in list(agent_connections.values()):
                                try: await ws.send_json(cmd)
                                except: pass
                    except Exception as e:
                        print(f"[Push] Error: {e}")
        except Exception as e:
            print(f"[Redis] Reconnecting: {e}")
            await asyncio.sleep(5)


# ── TASK SCHEDULER LOOP ───────────────────────────────────────
async def task_scheduler_loop():
    while True:
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Task).where(Task.status == "pending", Task.cancelled == False)
                )
                for task in result.scalars().all():
                    now = datetime.utcnow()
                    due = False
                    if task.trigger_type == "now":
                        due = True
                    elif task.trigger_type == "once" and task.scheduled_at and now >= task.scheduled_at:
                        due = True
                    if due:
                        task.status = "dispatched"
                        await db.commit()
                        if task.target_type == "all":
                            targets = list(agent_connections.keys())
                        elif task.target_type == "device" and task.target_id:
                            targets = [task.target_id] if task.target_id in agent_connections else []
                        else:
                            targets = list(agent_connections.keys())
                        for did in targets:
                            ws = agent_connections.get(did)
                            if ws:
                                try:
                                    await ws.send_json({"type":"run_task","data":{
                                        "task_id": task.id, "name": task.name,
                                        "script_type": task.script_type,
                                        "script_body": task.script_body,
                                        "trigger_type": task.trigger_type,
                                    }})
                                except: pass
        except Exception as e:
            print(f"[Scheduler] Error: {e}")
        await asyncio.sleep(30)


# ── AGENT WEBSOCKET ───────────────────────────────────────────
@app.websocket("/ws/agent/{device_id}")
async def agent_ws(websocket: WebSocket, device_id: str, token: str = ""):
    if token != AGENT_TOKEN:
        await websocket.close(code=4001)
        return
    await websocket.accept()
    agent_connections[device_id] = websocket
    print(f"[WS] Agent connected: {device_id}")
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Device).where(Device.device_id == device_id))
            device = result.scalar_one_or_none()
            if device:
                device.status = "online"
                device.last_seen = datetime.utcnow()
                await db.commit()
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=120)
                msg = json.loads(raw)
                t = msg.get("type")
                async with AsyncSessionLocal() as db:
                    if t == "heartbeat":
                        data = msg.get("data", {})
                        await db.execute(update(Device).where(Device.device_id == device_id).values(
                            status="online", last_seen=datetime.utcnow(),
                            cpu_percent=data.get("cpu_percent"),
                            ram_percent=data.get("ram_percent"),
                            disk_percent=data.get("disk_percent"),
                            battery_level=data.get("battery_level"),
                            battery_charging=data.get("battery_charging", False),
                            ip_address=data.get("ip_address", ""),
                            mac_address=data.get("mac") or data.get("mac_address"),
                        ))
                        await db.commit()
                        for ws in list(dashboard_connections.values()):
                            try: await ws.send_json({"type":"device_update","device_id":device_id,"data":data})
                            except: pass
                    elif t == "task_result":
                        data = msg.get("data", {})
                        task_id = data.get("task_id")
                        exit_code = data.get("exit_code", -1)
                        result_id = str(uuid.uuid4())
                        db.add(TaskResult(
                            id=result_id, task_id=task_id, device_id=device_id,
                            exit_code=exit_code, stdout=data.get("stdout",""),
                            stderr=data.get("stderr",""),
                            status="success" if exit_code == 0 else "failed",
                            started_at=datetime.utcnow(), completed_at=datetime.utcnow()
                        ))
                        await db.commit()
                        if exit_code != 0:
                            try:
                                from routes.email_svc import send_alert
                                dev_result = await db.execute(select(Device).where(Device.device_id == device_id))
                                dev = dev_result.scalar_one_or_none()
                                await send_alert("task_failed", {
                                    "task_name": task_id, "device": dev.hostname if dev else device_id,
                                    "timestamp": datetime.utcnow().isoformat(),
                                    "stderr": data.get("stderr","")[:500]
                                }, db)
                            except: pass
                    elif t == "task_output":
                        for ws in list(dashboard_connections.values()):
                            try: await ws.send_json(msg)
                            except: pass
                    elif t == "disk_scan":
                        data = msg.get("data", {})
                        await db.execute(update(Device).where(Device.device_id == device_id).values(
                            disk_details=data.get("details"), disk_scanned_at=datetime.utcnow()
                        ))
                        await db.commit()
                    elif t == "hw_report":
                        await db.execute(update(Device).where(Device.device_id == device_id).values(
                            hardware_info=msg.get("data", {}),
                            hardware_scanned_at=datetime.utcnow()
                        ))
                        await db.commit()
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS] Agent {device_id} error: {e}")
    finally:
        agent_connections.pop(device_id, None)
        async with AsyncSessionLocal() as db:
            await db.execute(update(Device).where(Device.device_id == device_id).values(status="offline"))
            await db.commit()
        print(f"[WS] Agent disconnected: {device_id}")


# ── DASHBOARD WEBSOCKET ───────────────────────────────────────
@app.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket):
    await websocket.accept()
    session_id = str(uuid.uuid4())
    dashboard_connections[session_id] = websocket
    try:
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"type": "ping"})
    except: pass
    finally:
        dashboard_connections.pop(session_id, None)


# ── AGENT CHECKIN ─────────────────────────────────────────────
@app.post("/api/agent/checkin")
async def agent_checkin(data: dict, x_agent_token: str = Header(None)):
    if x_agent_token != AGENT_TOKEN:
        from fastapi import HTTPException
        raise HTTPException(401, "Invalid token")
    device_id = data.get("device_id")
    if not device_id:
        from fastapi import HTTPException
        raise HTTPException(400, "device_id required")
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Device).where(Device.device_id == device_id))
        device = result.scalar_one_or_none()
        if not device:
            device = Device(
                device_id=device_id,
                hostname=data.get("hostname", device_id),
                platform=data.get("platform", "unknown"),
                status="online",
            )
            db.add(device)
        device.last_seen        = datetime.utcnow()
        device.status           = "online"
        device.hostname         = data.get("hostname", device.hostname)
        device.os_info          = data.get("os_info", "")
        device.ip_address       = data.get("ip_address", "")
        device.agent_version    = data.get("agent_version", "")
        device.battery_level    = data.get("battery_level")
        device.battery_charging = data.get("battery_charging", False)
        device.cpu_percent      = data.get("cpu_percent")
        device.ram_percent      = data.get("ram_percent")
        device.disk_percent     = data.get("disk_percent")
        if data.get("mac"): device.mac_address = data["mac"]
        await db.commit()
        # Get policy
        pol_result = await db.execute(select(Policy).where(Policy.device_id == None))
        policy = pol_result.scalar_one_or_none()
        # Get scheduled tasks
        task_result = await db.execute(
            select(Task).where(Task.status == "pending", Task.cancelled == False,
                               Task.trigger_type.in_(["interval","cron","event","once"]))
        )
        tasks_out = []
        for t in task_result.scalars().all():
            tasks_out.append({
                "task_id": t.id, "name": t.name, "trigger_type": t.trigger_type,
                "script_type": t.script_type, "script_body": t.script_body,
                "scheduled_at": t.scheduled_at.isoformat() if t.scheduled_at else None,
                "interval_seconds": t.interval_seconds, "cron_expression": t.cron_expression,
                "event_trigger": t.event_trigger,
            })
        return {
            "status": "ok",
            "ws_url": f"ws://{os.getenv('SERVER_IP','localhost')}:{os.getenv('BACKEND_PORT','8000')}/ws/agent/{device_id}",
            "scheduled_tasks": tasks_out,
            "policy": {
                "checkin_plugged_seconds": policy.checkin_plugged_seconds if policy else 30,
                "checkin_battery_100_80_seconds": policy.checkin_battery_100_80_seconds if policy else 60,
                "checkin_battery_79_50_seconds": policy.checkin_battery_79_50_seconds if policy else 180,
                "checkin_battery_49_20_seconds": policy.checkin_battery_49_20_seconds if policy else 300,
                "checkin_battery_19_10_seconds": policy.checkin_battery_19_10_seconds if policy else 600,
                "checkin_battery_9_0_seconds": policy.checkin_battery_9_0_seconds if policy else 900,
            },
            "update_available": None,
            "auto_update": False,
        }


@app.get("/api/health")
async def health(): return {"status": "ok"}
