"""Device notes — per-device freeform notes."""
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from models import DeviceNote
from database import get_db

router = APIRouter()

@router.get("/{device_id}")
async def get_notes(device_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DeviceNote).where(DeviceNote.device_id == device_id)
        .order_by(desc(DeviceNote.created_at))
    )
    return [{"id": n.id, "body": n.body, "author": n.author,
             "created_at": n.created_at.isoformat(),
             "updated_at": n.updated_at.isoformat()} for n in result.scalars().all()]

@router.post("/{device_id}")
async def add_note(device_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    n = DeviceNote(id=str(uuid.uuid4()), device_id=device_id,
                   body=data.get("body",""), author=data.get("author","admin"))
    db.add(n)
    await db.commit()
    return {"id": n.id}

@router.put("/{note_id}")
async def update_note(note_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DeviceNote).where(DeviceNote.id == note_id))
    n = result.scalar_one_or_none()
    if not n: raise HTTPException(404, "Note not found")
    n.body = data.get("body", n.body)
    n.updated_at = datetime.utcnow()
    await db.commit()
    return {"status": "updated"}

@router.delete("/{note_id}")
async def delete_note(note_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DeviceNote).where(DeviceNote.id == note_id))
    n = result.scalar_one_or_none()
    if not n: raise HTTPException(404, "Not found")
    await db.delete(n)
    await db.commit()
    return {"status": "deleted"}
