"""Device groups — assign devices to named groups."""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from models import DeviceGroup, Device
from database import get_db

router = APIRouter()

@router.get("/")
async def list_groups(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DeviceGroup).order_by(DeviceGroup.name))
    groups = result.scalars().all()
    out = []
    for g in groups:
        count_result = await db.execute(
            select(Device).where(Device.group_name == g.name)
        )
        out.append({"id": g.id, "name": g.name, "description": g.description,
                    "color": g.color, "device_count": len(count_result.scalars().all()),
                    "created_at": g.created_at.isoformat()})
    return out

@router.post("/")
async def create_group(data: dict, db: AsyncSession = Depends(get_db)):
    g = DeviceGroup(id=str(uuid.uuid4()), name=data["name"],
                    description=data.get("description",""), color=data.get("color","#00e5ff"))
    db.add(g)
    await db.commit()
    return {"id": g.id, "name": g.name}

@router.put("/{group_id}")
async def update_group(group_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DeviceGroup).where(DeviceGroup.id == group_id))
    g = result.scalar_one_or_none()
    if not g: raise HTTPException(404, "Group not found")
    for f in ("name","description","color"):
        if f in data: setattr(g, f, data[f])
    await db.commit()
    return {"status": "updated"}

@router.delete("/{group_id}")
async def delete_group(group_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DeviceGroup).where(DeviceGroup.id == group_id))
    g = result.scalar_one_or_none()
    if not g: raise HTTPException(404, "Not found")
    # Unassign devices
    await db.execute(update(Device).where(Device.group_name == g.name).values(group_name=None))
    await db.delete(g)
    await db.commit()
    return {"status": "deleted"}

@router.post("/{group_id}/assign")
async def assign_devices(group_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DeviceGroup).where(DeviceGroup.id == group_id))
    g = result.scalar_one_or_none()
    if not g: raise HTTPException(404, "Group not found")
    device_ids = data.get("device_ids", [])
    await db.execute(update(Device).where(Device.device_id.in_(device_ids)).values(group_name=g.name))
    await db.commit()
    return {"status": "assigned", "count": len(device_ids)}

@router.post("/device/{device_id}/unassign")
async def unassign_device(device_id: str, db: AsyncSession = Depends(get_db)):
    await db.execute(update(Device).where(Device.device_id == device_id).values(group_name=None))
    await db.commit()
    return {"status": "unassigned"}
