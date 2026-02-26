"""Software inventory — installed apps per device."""
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from models import SoftwareItem
from database import get_db

router = APIRouter()

@router.get("/{device_id}")
async def get_software(device_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SoftwareItem).where(SoftwareItem.device_id == device_id)
        .order_by(SoftwareItem.name)
    )
    return [{"id": s.id, "name": s.name, "version": s.version,
             "publisher": s.publisher, "install_date": s.install_date,
             "scanned_at": s.scanned_at.isoformat()} for s in result.scalars().all()]

@router.post("/{device_id}/report")
async def store_software(device_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    """Agent submits full software list — wipe and replace."""
    await db.execute(delete(SoftwareItem).where(SoftwareItem.device_id == device_id))
    apps = data.get("apps", [])
    for app in apps:
        db.add(SoftwareItem(
            id=str(uuid.uuid4()), device_id=device_id,
            name=app.get("name",""), version=app.get("version",""),
            publisher=app.get("publisher",""), install_date=app.get("install_date",""),
            scanned_at=datetime.utcnow()
        ))
    await db.commit()
    return {"status": "stored", "count": len(apps)}

@router.post("/{device_id}/scan")
async def request_scan(device_id: str):
    """Push a software scan request to the agent."""
    import json, main as _main
    if _main.redis_pool:
        await _main.redis_pool.publish("push_commands", json.dumps({
            "type": "software_scan", "device_id": device_id, "data": {}
        }))
    return {"status": "scan_requested"}
