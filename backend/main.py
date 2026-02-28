"""Sovereign RMM v5 — Enhanced Main Application
Action1-style RMM with update management, lockdown, and multi-platform support
"""

import asyncio, json, os, uuid, hashlib
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

import redis.asyncio as aioredis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, Request, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    Base, Device, Storage, Script, Task, TaskResult, SyncJob,
    InstalledSoftware, RunningProcess, UpdatePackage, PendingUpdate,
    LockdownRule, LogEntry, Setting
)
from database import engine, AsyncSessionLocal, get_db

# Environment variables
REDIS_URL = os.getenv("REDIS_URL", "")
AGENT_TOKEN = os.getenv("AGENT_TOKEN", "")
SERVER_IP = os.getenv("SERVER_IP", "localhost")
BACKEND_PORT = os.getenv("BACKEND_PORT", "8000")

# Global state
redis_pool = None
agent_connections: dict[str, WebSocket] = {}
dashboard_connections: dict[str, WebSocket] = {}

# Paths
UPDATE_CACHE_PATH = Path("/app/update-cache")
AGENT_BUILDS_PATH = Path("/app/agent-builds")
UPDATE_CACHE_PATH.mkdir(exist_ok=True)
AGENT_BUILDS_PATH.mkdir(exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    global redis_pool
    
    # Create database tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Connect to Redis
    redis_pool = await aioredis.from_url(REDIS_URL, decode_responses=True)
    
    # Seed default settings
    await seed_default_settings()
    
    # Start background tasks
    asyncio.create_task(task_scheduler_loop())
    asyncio.create_task(offline_detection_loop())
    asyncio.create_task(sync_coordinator_loop())
    asyncio.create_task(update_scanner_loop())
    asyncio.create_task(lockdown_enforcer_loop())
    
    yield
    
    # Cleanup
    await redis_pool.aclose()
    await engine.dispose()


# Create FastAPI app
app = FastAPI(
    title="Sovereign RMM v5",
    version="5.0.0",
    description="Action1-style RMM with update management and lockdown",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


# ── ROUTES ────────────────────────────────────────────────────
from routes import (
    auth, devices, storage, scripts, tasks, sync,
    dashboard, settings, hardware, policy, updates,
    lockdown, software, processes, builds
)

app.include_router(auth.router,      prefix="/api/auth",      tags=["Auth"])
app.include_router(devices.router,   prefix="/api/devices",   tags=["Devices"])
app.include_router(storage.router,   prefix="/api/storage",   tags=["Storage"])
app.include_router(scripts.router,   prefix="/api/scripts",   tags=["Scripts"])
app.include_router(tasks.router,     prefix="/api/tasks",     tags=["Tasks"])
app.include_router(sync.router,      prefix="/api/sync",      tags=["Sync"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(settings.router,  prefix="/api/settings",  tags=["Settings"])
app.include_router(hardware.router,  prefix="/api/hardware",  tags=["Hardware"])
app.include_router(policy.router,    prefix="/api/policy",    tags=["Policy"])
app.include_router(updates.router,   prefix="/api/updates",   tags=["Updates"])
app.include_router(lockdown.router,  prefix="/api/lockdown",  tags=["Lockdown"])
app.include_router(software.router,  prefix="/api/software",  tags=["Software"])
app.include_router(processes.router, prefix="/api/processes", tags=["Processes"])
app.include_router(builds.router,    prefix="/api/builds",    tags=["Builds"])


# ── HEALTH CHECK ──────────────────────────────────────────────
@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "5.0.0",
        "features": [
            "multi-platform-agents",
            "update-management",
            "device-lockdown",
            "auto-installer-generation"
        ]
    }


# ── SEED DEFAULT SETTINGS ─────────────────────────────────────
async def seed_default_settings():
    """Create default settings"""
    defaults = [
        ("server_ip", SERVER_IP, "Server IP Address", "network"),
        ("backend_port", BACKEND_PORT, "Backend Port", "network"),
        ("agent_token", AGENT_TOKEN, "Agent Authentication Token", "security"),
        ("admin_username", os.getenv("ADMIN_USERNAME", "admin"), "Admin Username", "auth"),
        ("global_lockdown", "false", "Global Lockdown Mode", "security"),
        ("auto_approve_updates", "false", "Auto Approve Updates", "updates"),
        ("update_check_interval", "3600", "Update Check Interval (seconds)", "updates"),
        ("storage_scan_depth", "3", "Storage Scan Depth", "storage"),
        ("auto_scan_usb", "true", "Auto Scan USB", "storage"),
    ]
    
    async with AsyncSessionLocal() as db:
        for key, value, description, category in defaults:
            result = await db.execute(select(Setting).where(Setting.key == key))
            if not result.scalar_one_or_none():
                setting = Setting(
                    key=key,
                    value=value,
                    description=description,
                    category=category
                )
                db.add(setting)
        await db.commit()


# ── WEBSOCKET ENDPOINTS ───────────────────────────────────────
@app.websocket("/ws/agent")
async def websocket_agent(websocket: WebSocket, token: str = Header(None)):
    """WebSocket endpoint for agents (all platforms)"""
    if token != AGENT_TOKEN:
        await websocket.close(code=1008, reason="Unauthorized")
        return
    
    await websocket.accept()
    device_id = None
    
    try:
        # First message should be registration
        data = await websocket.receive_json()
        
        if data.get("type") == "register":
            device_id = data.get("device_id")
            platform = data.get("platform", "unknown")
            
            agent_connections[device_id] = websocket
            
            # Update device status
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Device).where(Device.id == device_id)
                )
                device = result.scalar_one_or_none()
                if device:
                    device.status = "online"
                    device.last_seen = datetime.utcnow()
                    device.platform = platform
                    device.agent_version = data.get("agent_version", "unknown")
                    
                    # Check if device is locked down
                    if device.locked_down:
                        await websocket.send_json({
                            "type": "lockdown_active",
                            "message": "Device is in lockdown mode"
                        })
                    
                    # Check global lockdown
                    global_lockdown = await db.execute(
                        select(Setting).where(Setting.key == "global_lockdown")
                    )
                    setting = global_lockdown.scalar_one_or_none()
                    if setting and setting.value == "true":
                        await websocket.send_json({
                            "type": "global_lockdown_active",
                            "message": "System is in global lockdown mode"
                        })
                    
                    await db.commit()
            
            await websocket.send_json({
                "type": "connected",
                "message": "Agent connected successfully",
                "device_id": device_id
            })
            
            # Send any pending lockdown rules
            await send_lockdown_rules(device_id)
            
            # Send pending updates
            await send_pending_updates(device_id)
            
            # Handle messages
            while True:
                data = await websocket.receive_json()
                await handle_agent_message(device_id, data)
    
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        if device_id and device_id in agent_connections:
            del agent_connections[device_id]
            
            # Mark device offline
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Device).where(Device.id == device_id)
                )
                device = result.scalar_one_or_none()
                if device:
                    device.status = "offline"
                    await db.commit()


@app.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    """WebSocket endpoint for dashboard"""
    await websocket.accept()
    connection_id = str(uuid.uuid4())
    dashboard_connections[connection_id] = websocket
    
    try:
        while True:
            data = await websocket.receive_json()
            # Handle dashboard commands
    except WebSocketDisconnect:
        pass
    finally:
        if connection_id in dashboard_connections:
            del dashboard_connections[connection_id]


# ── MESSAGE HANDLERS ──────────────────────────────────────────
async def handle_agent_message(device_id: str, data: dict):
    """Handle messages from agents"""
    msg_type = data.get("type")
    
    if msg_type == "heartbeat":
        await handle_heartbeat(device_id, data)
    
    elif msg_type == "stats_update":
        await handle_stats_update(device_id, data)
    
    elif msg_type == "storage_detected":
        await handle_storage_detected(device_id, data)
    
    elif msg_type == "task_result":
        await handle_task_result(device_id, data)
    
    elif msg_type == "software_inventory":
        await handle_software_inventory(device_id, data)
    
    elif msg_type == "process_list":
        await handle_process_list(device_id, data)
    
    elif msg_type == "update_check_result":
        await handle_update_check_result(device_id, data)
    
    elif msg_type == "update_progress":
        await handle_update_progress(device_id, data)
    
    elif msg_type == "lockdown_violation":
        await handle_lockdown_violation(device_id, data)


async def handle_heartbeat(device_id: str, data: dict):
    """Handle heartbeat from agent"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Device).where(Device.id == device_id)
        )
        device = result.scalar_one_or_none()
        if device:
            device.last_seen = datetime.utcnow()
            device.last_gpupdate = data.get("last_gpupdate")
            device.pending_restart = data.get("pending_restart", False)
            await db.commit()


async def handle_stats_update(device_id: str, data: dict):
    """Handle system statistics update"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Device).where(Device.id == device_id)
        )
        device = result.scalar_one_or_none()
        if device:
            stats = data.get("stats", {})
            device.cpu_usage = stats.get("cpu_usage")
            device.ram_used = stats.get("ram_used")
            device.ram_total = stats.get("ram_total")
            device.disk_used = stats.get("disk_used")
            device.disk_total = stats.get("disk_total")
            device.network_sent = stats.get("network_sent")
            device.network_recv = stats.get("network_recv")
            await db.commit()
    
    # Broadcast to dashboards
    await broadcast_to_dashboards({
        "type": "stats_updated",
        "device_id": device_id,
        "stats": data.get("stats")
    })


async def handle_storage_detected(device_id: str, data: dict):
    """Handle storage detection"""
    storage_data = data.get("storage")
    
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Storage).where(
                Storage.serial_number == storage_data.get("serial_number")
            )
        )
        storage = result.scalar_one_or_none()
        
        if not storage:
            storage = Storage(
                device_id=device_id,
                serial_number=storage_data.get("serial_number"),
                disk_signature=storage_data.get("disk_signature"),
                model=storage_data.get("model"),
                drive_letter=storage_data.get("drive_letter"),
                label=storage_data.get("label"),
                total_size=storage_data.get("total_size"),
                used_size=storage_data.get("used_size"),
                storage_type=storage_data.get("storage_type"),
                folder_tree=storage_data.get("folder_tree"),
                connected=True,
                last_seen=datetime.utcnow()
            )
            db.add(storage)
        else:
            storage.drive_letter = storage_data.get("drive_letter")
            storage.connected = True
            storage.last_seen = datetime.utcnow()
            storage.folder_tree = storage_data.get("folder_tree")
        
        await db.commit()
    
    await broadcast_to_dashboards({
        "type": "storage_updated",
        "device_id": device_id,
        "storage": storage_data
    })


async def handle_task_result(device_id: str, data: dict):
    """Handle task execution result"""
    task_id = data.get("task_id")
    
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Task).where(Task.id == task_id)
        )
        task = result.scalar_one_or_none()
        if task:
            task.last_run = datetime.utcnow()
            task.last_status = data.get("status")
            task.last_output = data.get("output")
            
            task_result = TaskResult(
                task_id=task_id,
                status=data.get("status"),
                output=data.get("output"),
                error=data.get("error")
            )
            db.add(task_result)
            await db.commit()


async def handle_software_inventory(device_id: str, data: dict):
    """Handle software inventory update"""
    software_list = data.get("software", [])
    
    async with AsyncSessionLocal() as db:
        # Clear old inventory
        await db.execute(
            delete(InstalledSoftware).where(InstalledSoftware.device_id == device_id)
        )
        
        # Add new inventory
        for sw in software_list:
            software = InstalledSoftware(
                device_id=device_id,
                name=sw.get("name"),
                version=sw.get("version"),
                publisher=sw.get("publisher"),
                install_location=sw.get("install_location"),
                size=sw.get("size")
            )
            db.add(software)
        
        await db.commit()


async def handle_process_list(device_id: str, data: dict):
    """Handle running processes update"""
    processes = data.get("processes", [])
    
    async with AsyncSessionLocal() as db:
        # Clear old processes
        await db.execute(
            delete(RunningProcess).where(RunningProcess.device_id == device_id)
        )
        
        # Add current processes
        for proc in processes:
            process = RunningProcess(
                device_id=device_id,
                name=proc.get("name"),
                pid=proc.get("pid"),
                cpu_percent=proc.get("cpu_percent"),
                memory_mb=proc.get("memory_mb"),
                username=proc.get("username"),
                status=proc.get("status")
            )
            db.add(process)
        
        await db.commit()


async def handle_update_check_result(device_id: str, data: dict):
    """Handle update check results from agent"""
    updates = data.get("updates", [])
    
    async with AsyncSessionLocal() as db:
        for update_info in updates:
            # Check if update package exists
            result = await db.execute(
                select(UpdatePackage).where(
                    UpdatePackage.kb_number == update_info.get("kb_number")
                ).where(
                    UpdatePackage.platform == data.get("platform")
                )
            )
            package = result.scalar_one_or_none()
            
            if not package:
                # Create new update package
                package = UpdatePackage(
                    name=update_info.get("name"),
                    version=update_info.get("version"),
                    platform=data.get("platform"),
                    package_type=update_info.get("type"),
                    description=update_info.get("description"),
                    severity=update_info.get("severity"),
                    kb_number=update_info.get("kb_number"),
                    file_size=update_info.get("size"),
                    approved=False
                )
                db.add(package)
                await db.flush()
            
            # Create pending update
            pending = PendingUpdate(
                device_id=device_id,
                package_id=package.id,
                status="pending"
            )
            db.add(pending)
        
        await db.commit()


async def handle_update_progress(device_id: str, data: dict):
    """Handle update installation progress"""
    update_id = data.get("update_id")
    progress = data.get("progress")
    status = data.get("status")
    
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PendingUpdate).where(PendingUpdate.id == update_id)
        )
        pending = result.scalar_one_or_none()
        if pending:
            pending.progress = progress
            pending.status = status
            if status == "installed":
                pending.installed_at = datetime.utcnow()
            await db.commit()
    
    # Broadcast to dashboards
    await broadcast_to_dashboards({
        "type": "update_progress",
        "device_id": device_id,
        "update_id": update_id,
        "progress": progress,
        "status": status
    })


async def handle_lockdown_violation(device_id: str, data: dict):
    """Handle lockdown rule violation"""
    violation_type = data.get("violation_type")
    details = data.get("details")
    
    # Log violation
    async with AsyncSessionLocal() as db:
        log_entry = LogEntry(
            device_id=device_id,
            level="warning",
            message=f"Lockdown violation: {violation_type}",
            details=details
        )
        db.add(log_entry)
        await db.commit()
    
    # Alert dashboard
    await broadcast_to_dashboards({
        "type": "lockdown_violation",
        "device_id": device_id,
        "violation_type": violation_type,
        "details": details,
        "timestamp": datetime.utcnow().isoformat()
    })


async def send_lockdown_rules(device_id: str):
    """Send lockdown rules to device"""
    if device_id not in agent_connections:
        return
    
    async with AsyncSessionLocal() as db:
        # Get device
        result = await db.execute(
            select(Device).where(Device.id == device_id)
        )
        device = result.scalar_one_or_none()
        if not device:
            return
        
        # Get applicable lockdown rules
        rules_query = await db.execute(
            select(LockdownRule).where(
                (LockdownRule.global_rule == True) |
                (LockdownRule.device_ids.contains([device_id]))
            ).where(
                LockdownRule.enabled == True
            )
        )
        rules = rules_query.scalars().all()
        
        if rules:
            await agent_connections[device_id].send_json({
                "type": "lockdown_rules",
                "rules": [
                    {
                        "id": rule.id,
                        "rule_type": rule.rule_type,
                        "config": rule.config
                    }
                    for rule in rules
                ]
            })


async def send_pending_updates(device_id: str):
    """Send pending updates to device"""
    if device_id not in agent_connections:
        return
    
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PendingUpdate).join(UpdatePackage).where(
                PendingUpdate.device_id == device_id
            ).where(
                PendingUpdate.status == "pending"
            ).where(
                UpdatePackage.approved == True
            )
        )
        pending_updates = result.scalars().all()
        
        if pending_updates:
            updates_to_send = []
            for pending in pending_updates:
                package = pending.package
                updates_to_send.append({
                    "update_id": pending.id,
                    "package_id": package.id,
                    "name": package.name,
                    "version": package.version,
                    "download_url": f"/api/updates/download/{package.id}",
                    "file_hash": package.file_hash,
                    "file_size": package.file_size
                })
            
            await agent_connections[device_id].send_json({
                "type": "install_updates",
                "updates": updates_to_send
            })


async def broadcast_to_dashboards(message: dict):
    """Broadcast message to all connected dashboards"""
    for websocket in dashboard_connections.values():
        try:
            await websocket.send_json(message)
        except:
            pass


# ── BACKGROUND TASKS ──────────────────────────────────────────
async def task_scheduler_loop():
    """Check for scheduled tasks"""
    while True:
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Task).where(
                        Task.enabled == True,
                        Task.schedule != "manual"
                    )
                )
                tasks = result.scalars().all()
                
                for task in tasks:
                    if should_run_task(task):
                        if task.device_id in agent_connections:
                            script = task.script
                            await agent_connections[task.device_id].send_json({
                                "type": "execute_task",
                                "task_id": task.id,
                                "script_id": script.id,
                                "script_content": script.content,
                                "script_type": script.script_type
                            })
        except Exception as e:
            print(f"Task scheduler error: {e}")
        
        await asyncio.sleep(60)


async def offline_detection_loop():
    """Detect offline devices"""
    while True:
        try:
            async with AsyncSessionLocal() as db:
                threshold = datetime.utcnow() - timedelta(minutes=5)
                await db.execute(
                    update(Device)
                    .where(Device.last_seen < threshold)
                    .values(status="offline")
                )
                await db.commit()
        except Exception as e:
            print(f"Offline detection error: {e}")
        
        await asyncio.sleep(60)


async def sync_coordinator_loop():
    """Coordinate file synchronization"""
    while True:
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(SyncJob).where(
                        SyncJob.enabled == True,
                        SyncJob.status == "pending"
                    )
                )
                jobs = result.scalars().all()
                
                for job in jobs:
                    # Process sync job
                    pass
        except Exception as e:
            print(f"Sync coordinator error: {e}")
        
        await asyncio.sleep(30)


async def update_scanner_loop():
    """Scan for available updates"""
    while True:
        try:
            # Trigger update check on all online devices
            for device_id, websocket in agent_connections.items():
                try:
                    await websocket.send_json({
                        "type": "check_updates"
                    })
                except:
                    pass
        except Exception as e:
            print(f"Update scanner error: {e}")
        
        await asyncio.sleep(3600)  # Every hour


async def lockdown_enforcer_loop():
    """Enforce lockdown rules"""
    while True:
        try:
            async with AsyncSessionLocal() as db:
                # Check for newly locked down devices
                result = await db.execute(
                    select(Device).where(Device.locked_down == True)
                )
                locked_devices = result.scalars().all()
                
                for device in locked_devices:
                    if device.id in agent_connections:
                        await send_lockdown_rules(device.id)
        except Exception as e:
            print(f"Lockdown enforcer error: {e}")
        
        await asyncio.sleep(60)


def should_run_task(task):
    """Check if task should run"""
    if not task.last_run:
        return True
    
    if task.schedule == "hourly":
        return (datetime.utcnow() - task.last_run).total_seconds() > 3600
    elif task.schedule == "daily":
        return (datetime.utcnow() - task.last_run).total_seconds() > 86400
    
    return False


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
