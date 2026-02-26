"""Custom alert rules — threshold-based alerts on metrics."""
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import AlertRule
from database import get_db

router = APIRouter()

@router.get("/")
async def list_rules(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AlertRule).order_by(AlertRule.created_at))
    return [{"id": r.id, "name": r.name, "metric": r.metric, "operator": r.operator,
             "threshold": r.threshold, "duration_minutes": r.duration_minutes,
             "target_type": r.target_type, "target_id": r.target_id,
             "action": r.action, "active": r.active,
             "last_fired": r.last_fired.isoformat() if r.last_fired else None,
             "created_at": r.created_at.isoformat()} for r in result.scalars().all()]

@router.post("/")
async def create_rule(data: dict, db: AsyncSession = Depends(get_db)):
    r = AlertRule(
        id=str(uuid.uuid4()), name=data["name"], metric=data["metric"],
        operator=data.get("operator","gt"), threshold=data.get("threshold",90),
        duration_minutes=data.get("duration_minutes",5),
        target_type=data.get("target_type","all"), target_id=data.get("target_id"),
        action=data.get("action","email"), active=True,
    )
    db.add(r)
    await db.commit()
    return {"id": r.id}

@router.put("/{rule_id}")
async def update_rule(rule_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AlertRule).where(AlertRule.id == rule_id))
    r = result.scalar_one_or_none()
    if not r: raise HTTPException(404, "Rule not found")
    for f in ("name","metric","operator","threshold","duration_minutes","target_type","target_id","action","active"):
        if f in data: setattr(r, f, data[f])
    await db.commit()
    return {"status": "updated"}

@router.delete("/{rule_id}")
async def delete_rule(rule_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AlertRule).where(AlertRule.id == rule_id))
    r = result.scalar_one_or_none()
    if not r: raise HTTPException(404, "Not found")
    await db.delete(r)
    await db.commit()
    return {"status": "deleted"}
