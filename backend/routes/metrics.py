"""Performance history — store and query CPU/RAM/disk over time."""
import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from models import MetricHistory
from database import get_db

router = APIRouter()

@router.get("/{device_id}")
async def get_metrics(device_id: str, hours: int = 24, db: AsyncSession = Depends(get_db)):
    since = datetime.utcnow() - timedelta(hours=hours)
    result = await db.execute(
        select(MetricHistory)
        .where(MetricHistory.device_id == device_id, MetricHistory.recorded_at >= since)
        .order_by(MetricHistory.recorded_at)
    )
    rows = result.scalars().all()
    return [{"t": r.recorded_at.isoformat(), "cpu": r.cpu, "ram": r.ram,
             "disk": r.disk, "battery": r.battery} for r in rows]

@router.post("/{device_id}")
async def record_metric(device_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    db.add(MetricHistory(
        id=str(uuid.uuid4()), device_id=device_id,
        cpu=data.get("cpu"), ram=data.get("ram"),
        disk=data.get("disk"), battery=data.get("battery"),
    ))
    # Prune records older than 30 days
    cutoff = datetime.utcnow() - timedelta(days=30)
    await db.execute(delete(MetricHistory).where(
        MetricHistory.device_id == device_id, MetricHistory.recorded_at < cutoff
    ))
    await db.commit()
    return {"status": "ok"}

@router.delete("/{device_id}")
async def clear_metrics(device_id: str, db: AsyncSession = Depends(get_db)):
    await db.execute(delete(MetricHistory).where(MetricHistory.device_id == device_id))
    await db.commit()
    return {"status": "cleared"}
