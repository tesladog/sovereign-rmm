"""Process manager — list and kill processes remotely."""
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db

router = APIRouter()

@router.get("/{device_id}")
async def get_processes(device_id: str):
    """Request live process list from agent via Redis pub/sub."""
    import main as _main
    ws = _main.agent_connections.get(device_id)
    if not ws:
        raise HTTPException(503, "Device offline")
    try:
        await ws.send_json({"type": "get_processes", "data": {}})
        return {"status": "requested", "message": "Process list will arrive via WebSocket"}
    except Exception as e:
        raise HTTPException(500, str(e))

@router.post("/{device_id}/kill")
async def kill_process(device_id: str, data: dict):
    """Send kill signal for a PID to the agent."""
    import main as _main
    ws = _main.agent_connections.get(device_id)
    if not ws:
        raise HTTPException(503, "Device offline")
    pid = data.get("pid")
    name = data.get("name", "")
    if not pid:
        raise HTTPException(400, "pid required")
    try:
        await ws.send_json({"type": "kill_process", "data": {"pid": pid, "name": name}})
        return {"status": "kill_sent", "pid": pid}
    except Exception as e:
        raise HTTPException(500, str(e))

@router.post("/{device_id}/action")
async def quick_action(device_id: str, data: dict):
    """Quick actions: shutdown, restart, lock."""
    import main as _main
    ws = _main.agent_connections.get(device_id)
    if not ws:
        raise HTTPException(503, "Device offline or not connected via WebSocket")
    action = data.get("action")
    if action not in ("shutdown", "restart", "lock", "sleep"):
        raise HTTPException(400, f"Unknown action: {action}")
    try:
        await ws.send_json({"type": "quick_action", "data": {"action": action}})
        return {"status": "sent", "action": action}
    except Exception as e:
        raise HTTPException(500, str(e))
