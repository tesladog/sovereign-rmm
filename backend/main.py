"""SOVEREIGN RMM v2 — Main Application"""

import asyncio, json, os, uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import redis.asyncio as aioredis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, update

from models import (Base, Device, Task, TaskResult, LogEntry, Policy,
                    Setting, AgentVersion, MetricHistory, AlertRule)
from database import engine, AsyncSessionLocal, get_db

REDIS_URL   = os.getenv("REDIS_URL", "")
AGENT_TOKEN = os.getenv("AGENT_TOKEN", "")

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
    asyncio.create_task(offline_detection_loop())
    asyncio.create_task(alert_rule_loop())
    asyncio.create_task(scheduled_report_loop())
    yield
    await redis_pool.aclose()
    await engine.dispose()


app = FastAPI(title="Sovereign RMM v2", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


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
from routes import (auth, devices, tasks, policies, dashboard, settings,
                    scripts, inventory, builds, lockdown, wol,
                    email_svc, hardware, backup, metrics, software,
                    processes, groups, notes, alert_rules, reports)

app.include_router(auth.router,         prefix="/api/auth",         tags=["Auth"])
app.include_router(devices.router,      prefix="/api/devices",      tags=["Devices"])
app.include_router(tasks.router,        prefix="/api/tasks",        tags=["Tasks"])
app.include_router(policies.router,     prefix="/api/policies",     tags=["Policies"])
app.include_router(dashboard.router,    prefix="/api/dashboard",    tags=["Dashboard"])
app.include_router(settings.router,     prefix="/api/settings",     tags=["Settings"])
app.include_router(scripts.router,      prefix="/api/scripts",      tags=["Scripts"])
app.include_router(inventory.router,    prefix="/api/inventory",    tags=["Inventory"])
app.include_router(builds.router,       prefix="/api/builds",       tags=["Builds"])
app.include_router(lockdown.router,     prefix="/api/lockdown",     tags=["Lockdown"])
app.include_router(wol.router,          prefix="/api/wol",          tags=["WoL"])
app.include_router(email_svc.router,    prefix="/api/email",        tags=["Email"])
app.include_router(hardware.router,     prefix="/api/hardware",     tags=["Hardware"])
app.include_router(backup.router,       prefix="/api/backup",       tags=["Backup"])
app.include_router(metrics.router,      prefix="/api/metrics",      tags=["Metrics"])
app.include_router(software.router,     prefix="/api/software",     tags=["Software"])
app.include_router(processes.router,    prefix="/api/processes",    tags=["Processes"])
app.include_router(groups.router,       prefix="/api/groups",       tags=["Groups"])
app.include_router(notes.router,        prefix="/api/notes",        tags=["Notes"])
app.include_router(alert_rules.router,  prefix="/api/alert-rules",  tags=["AlertRules"])
app.include_router(reports.router,      prefix="/api/reports",      tags=["Reports"])


# ── SEED SETTINGS ─────────────────────────────────────────────
async def seed_default_settings():
    defaults = [
        ("server_ip",        os.getenv("SERVER_IP","192.168.5.199"), "Server Local IP",   "network"),
        ("vpn_ip",           "100.125.120.81",                        "Server VPN IP",     "network"),
        ("backend_port",     os.getenv("BACKEND_PORT","8000"),        "Backend Port",      "network"),
        ("agent_token",      AGENT_TOKEN,                             "Agent Token",       "security"),
        ("admin_username",   os.getenv("ADMIN_USERNAME","admin"),     "Admin Username",    "auth"),
        ("smtp_host",        "",                                      "SMTP Host",         "email"),
        ("smtp_port",        "587",                                   "SMTP Port",         "email"),
        ("smtp_user",        "",                                      "SMTP User",         "email"),
        ("smtp_pass",        "",                                      "SMTP Password",     "email"),
        ("alert_email",      "",                                      "Alert Email",       "email"),
        ("lockdown_enabled", "false",                                 "Lockdown Mode",     "security"),
        ("offline_minutes",  "10",                                    "Offline After (min)","monitoring"),
        ("report_schedule",  "weekly",                                "Report Schedule",   "reports"),
        ("dark_mode",        "true",                                  "Dark Mode",         "appearance"),
        ("theme_accent",     "#00e5ff",                               "Accent Color",      "appearance"),
    ]
    async with AsyncSessionLocal() as db:
        for key, value, label, category in defaults:
            r = await db.execute(select(Setting).where(Setting.key == key))
            if not r.scalar_one_or_none():
                db.add(Setting(key=key, value=value, label=label, category=category))
        await db.commit()


# ── REDIS PUSH LISTENER ───────────────────────────────────────
async def listen_for_push_commands():
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
                            await agent_connections[device_id].send_json(cmd)
                        elif not device_id:
                            for ws in list(agent_connections.values()):
                                try: await ws.send_json(cmd)
                                except: pass
                    except Exception as e:
                        print(f"[Push] {e}")
        except Exception as e:
            print(f"[Redis] Reconnecting: {e}")
            await asyncio.sleep(5)


# ── TASK SCHEDULER ────────────────────────────────────────────
async def task_scheduler_loop():
    while True:
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Task).where(Task.status == "pending", Task.cancelled == False)
                )
                for task in result.scalars().all():
                    now = datetime.utcnow()
                    due = (task.trigger_type == "now" or
                           (task.trigger_type == "once" and task.scheduled_at and now >= task.scheduled_at))
                    if due:
                        task.status = "dispatched"
                        await db.commit()
                        if task.target_type == "device" and task.target_id:
                            targets = [task.target_id] if task.target_id in agent_connections else []
                        else:
                            targets = list(agent_connections.keys())
                        payload = {"type": "run_task", "data": {
                            "task_id": task.id, "name": task.name,
                            "script_type": task.script_type, "script_body": task.script_body,
                        }}
                        for did in targets:
                            ws = agent_connections.get(did)
                            if ws:
                                try: await ws.send_json(payload)
                                except: pass
        except Exception as e:
            print(f"[Scheduler] {e}")
        await asyncio.sleep(30)


# ── OFFLINE DETECTION ─────────────────────────────────────────
async def offline_detection_loop():
    """Mark devices offline if they haven't checked in."""
    await asyncio.sleep(60)
    while True:
        try:
            async with AsyncSessionLocal() as db:
                settings_result = await db.execute(select(Setting).where(Setting.key == "offline_minutes"))
                s = settings_result.scalar_one_or_none()
                minutes = int(s.value) if s else 10
                cutoff = datetime.utcnow() - timedelta(minutes=minutes)
                result = await db.execute(
                    select(Device).where(Device.status == "online", Device.last_seen < cutoff)
                )
                for device in result.scalars().all():
                    if device.device_id not in agent_connections:
                        device.status = "offline"
                        for ws in list(dashboard_connections.values()):
                            try: await ws.send_json({"type":"device_offline","device_id":device.device_id})
                            except: pass
                        # Fire offline alert emails
                        try:
                            from routes.email_svc import send_alert
                            await send_alert("device_offline", {
                                "device": device.label or device.hostname,
                                "last_seen": device.last_seen.isoformat() if device.last_seen else "unknown",
                                "ip": device.ip_address or "unknown",
                            }, db)
                        except: pass
                await db.commit()
        except Exception as e:
            print(f"[OfflineDetect] {e}")
        await asyncio.sleep(60)


# ── ALERT RULE CHECKER ────────────────────────────────────────
async def alert_rule_loop():
    """Check custom metric alert rules every 2 minutes."""
    await asyncio.sleep(90)
    while True:
        try:
            async with AsyncSessionLocal() as db:
                rules_result = await db.execute(select(AlertRule).where(AlertRule.active == True))
                rules = rules_result.scalars().all()
                devices_result = await db.execute(select(Device).where(Device.status == "online"))
                devices = devices_result.scalars().all()
                for rule in rules:
                    # Throttle: don't fire same rule more than once per hour
                    if rule.last_fired and (datetime.utcnow() - rule.last_fired).seconds < 3600:
                        continue
                    for device in devices:
                        if rule.target_type == "device" and rule.target_id and rule.target_id != device.device_id:
                            continue
                        val = {"cpu": device.cpu_percent, "ram": device.ram_percent,
                               "disk": device.disk_percent, "battery": device.battery_level}.get(rule.metric)
                        if val is None: continue
                        triggered = (
                            (rule.operator == "gt" and val > rule.threshold) or
                            (rule.operator == "lt" and val < rule.threshold) or
                            (rule.operator == "eq" and abs(val - rule.threshold) < 0.5)
                        )
                        if triggered:
                            rule.last_fired = datetime.utcnow()
                            if rule.action == "email":
                                try:
                                    from routes.email_svc import send_alert
                                    await send_alert("task_failed", {
                                        "task_name": f"Alert: {rule.name}",
                                        "device": device.label or device.hostname,
                                        "timestamp": datetime.utcnow().isoformat(),
                                        "stderr": f"{rule.metric} is {val:.1f}% (threshold: {rule.operator} {rule.threshold}%)"
                                    }, db)
                                except: pass
                            # Log it
                            db.add(LogEntry(
                                id=str(uuid.uuid4()), device_id=device.device_id,
                                level="warn", source="alert_rule",
                                message=f"Alert '{rule.name}': {rule.metric}={val:.1f}% {rule.operator} {rule.threshold}%"
                            ))
                await db.commit()
        except Exception as e:
            print(f"[AlertRules] {e}")
        await asyncio.sleep(120)


# ── SCHEDULED REPORT LOOP ─────────────────────────────────────
async def scheduled_report_loop():
    """Send weekly summary report on Mondays at 8am UTC."""
    while True:
        try:
            now = datetime.utcnow()
            if now.weekday() == 0 and now.hour == 8 and now.minute < 5:
                async with AsyncSessionLocal() as db:
                    s = await db.execute(select(Setting).where(Setting.key=="report_schedule"))
                    setting = s.scalar_one_or_none()
                    if not setting or setting.value != "off":
                        from routes.reports import build_report_html
                        from routes.email_svc import get_smtp_settings, send_email_raw
                        html = await build_report_html(db)
                        smtp = await get_smtp_settings(db)
                        to = smtp.get("alert_email","")
                        if to:
                            await send_email_raw(smtp, to,
                                f"[Sovereign RMM] Weekly Report — {now.strftime('%B %d, %Y')}", html)
        except Exception as e:
            print(f"[Report] {e}")
        await asyncio.sleep(300)


# ── AGENT WEBSOCKET ───────────────────────────────────────────
@app.websocket("/ws/agent/{device_id}")
async def agent_ws(websocket: WebSocket, device_id: str, token: str = ""):
    if token != AGENT_TOKEN:
        await websocket.close(code=4001)
        return
    await websocket.accept()
    agent_connections[device_id] = websocket
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Device).where(Device.device_id == device_id))
        dev = r.scalar_one_or_none()
        if dev:
            dev.status = "online"
            dev.last_seen = datetime.utcnow()
            await db.commit()
    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=120)
                msg = json.loads(raw)
                t = msg.get("type")
                async with AsyncSessionLocal() as db:
                    if t == "heartbeat":
                        d = msg.get("data", {})
                        await db.execute(update(Device).where(Device.device_id == device_id).values(
                            status="online", last_seen=datetime.utcnow(),
                            cpu_percent=d.get("cpu_percent"), ram_percent=d.get("ram_percent"),
                            disk_percent=d.get("disk_percent"), battery_level=d.get("battery_level"),
                            battery_charging=d.get("battery_charging", False),
                            ip_address=d.get("ip_address",""),
                            mac_address=d.get("mac") or d.get("mac_address"),
                        ))
                        # Record metric history
                        db.add(MetricHistory(
                            id=str(uuid.uuid4()), device_id=device_id,
                            cpu=d.get("cpu_percent"), ram=d.get("ram_percent"),
                            disk=d.get("disk_percent"), battery=d.get("battery_level"),
                        ))
                        await db.commit()
                        for ws in list(dashboard_connections.values()):
                            try: await ws.send_json({"type":"device_update","device_id":device_id,"data":d})
                            except: pass

                    elif t == "task_result":
                        d = msg.get("data", {})
                        exit_code = d.get("exit_code", -1)
                        db.add(TaskResult(
                            id=str(uuid.uuid4()), task_id=d.get("task_id",""),
                            device_id=device_id, exit_code=exit_code,
                            stdout=d.get("stdout",""), stderr=d.get("stderr",""),
                            status="success" if exit_code == 0 else "failed",
                            started_at=datetime.utcnow(), completed_at=datetime.utcnow()
                        ))
                        await db.commit()
                        if exit_code != 0:
                            try:
                                from routes.email_svc import send_alert
                                dev_r = await db.execute(select(Device).where(Device.device_id == device_id))
                                dev = dev_r.scalar_one_or_none()
                                await send_alert("task_failed", {
                                    "task_name": d.get("task_id",""), "device": dev.hostname if dev else device_id,
                                    "timestamp": datetime.utcnow().isoformat(), "stderr": d.get("stderr","")[:500]
                                }, db)
                            except: pass

                    elif t == "task_output":
                        for ws in list(dashboard_connections.values()):
                            try: await ws.send_json(msg)
                            except: pass

                    elif t == "disk_scan":
                        await db.execute(update(Device).where(Device.device_id == device_id).values(
                            disk_details=msg.get("data",{}).get("details"),
                            disk_scanned_at=datetime.utcnow()
                        ))
                        await db.commit()

                    elif t == "hw_report":
                        await db.execute(update(Device).where(Device.device_id == device_id).values(
                            hardware_info=msg.get("data",{}), hardware_scanned_at=datetime.utcnow()
                        ))
                        await db.commit()

                    elif t == "software_report":
                        from routes.software import store_software
                        await store_software(device_id, msg.get("data",{}), db)

                    elif t == "process_list":
                        # Forward to all dashboard connections
                        for ws in list(dashboard_connections.values()):
                            try: await ws.send_json({"type":"process_list","device_id":device_id,"data":msg.get("data",[])})
                            except: pass

                    elif t == "log":
                        d = msg.get("data", {})
                        db.add(LogEntry(
                            id=str(uuid.uuid4()), device_id=device_id,
                            level=d.get("level","info"), message=d.get("message",""),
                            source="agent"
                        ))
                        await db.commit()

            except asyncio.TimeoutError:
                await websocket.send_json({"type":"ping"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS] Agent {device_id}: {e}")
    finally:
        agent_connections.pop(device_id, None)
        async with AsyncSessionLocal() as db:
            await db.execute(update(Device).where(Device.device_id == device_id).values(status="offline"))
            await db.commit()


# ── DASHBOARD WEBSOCKET ───────────────────────────────────────
@app.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket):
    await websocket.accept()
    sid = str(uuid.uuid4())
    dashboard_connections[sid] = websocket
    try:
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"type":"ping"})
    except: pass
    finally:
        dashboard_connections.pop(sid, None)


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
        r = await db.execute(select(Device).where(Device.device_id == device_id))
        device = r.scalar_one_or_none()
        if not device:
            device = Device(device_id=device_id, hostname=data.get("hostname",device_id),
                           platform=data.get("platform","unknown"), status="online")
            db.add(device)
        device.last_seen = datetime.utcnow()
        device.status    = "online"
        device.hostname  = data.get("hostname", device.hostname)
        device.os_info   = data.get("os_info","")
        device.ip_address = data.get("ip_address","")
        device.agent_version = data.get("agent_version","")
        device.battery_level = data.get("battery_level")
        device.battery_charging = data.get("battery_charging", False)
        device.cpu_percent = data.get("cpu_percent")
        device.ram_percent = data.get("ram_percent")
        device.disk_percent = data.get("disk_percent")
        if data.get("mac"): device.mac_address = data["mac"]
        await db.commit()
        pol = (await db.execute(select(Policy).where(Policy.device_id == None))).scalar_one_or_none()
        task_result = await db.execute(
            select(Task).where(Task.status=="pending", Task.cancelled==False,
                               Task.trigger_type.in_(["interval","cron","event","once"]))
        )
        tasks_out = [{"task_id":t.id,"name":t.name,"trigger_type":t.trigger_type,
                      "script_type":t.script_type,"script_body":t.script_body,
                      "scheduled_at":t.scheduled_at.isoformat() if t.scheduled_at else None,
                      "interval_seconds":t.interval_seconds,"cron_expression":t.cron_expression,
                      "event_trigger":t.event_trigger} for t in task_result.scalars().all()]
        return {
            "status": "ok",
            "ws_url": f"ws://{os.getenv('SERVER_IP','localhost')}:{os.getenv('BACKEND_PORT','8000')}/ws/agent/{device_id}",
            "scheduled_tasks": tasks_out,
            "policy": {
                "checkin_plugged_seconds": pol.checkin_plugged_seconds if pol else 30,
                "checkin_battery_100_80_seconds": pol.checkin_battery_100_80_seconds if pol else 60,
                "checkin_battery_79_50_seconds": pol.checkin_battery_79_50_seconds if pol else 180,
                "checkin_battery_49_20_seconds": pol.checkin_battery_49_20_seconds if pol else 300,
                "checkin_battery_19_10_seconds": pol.checkin_battery_19_10_seconds if pol else 600,
                "checkin_battery_9_0_seconds": pol.checkin_battery_9_0_seconds if pol else 900,
            },
        }


@app.get("/api/health")
async def health(): return {"status": "ok"}
