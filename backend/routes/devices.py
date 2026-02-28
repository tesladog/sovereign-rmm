from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import sys
sys.path.append('..')
from database import get_db
from models import Device
router = APIRouter()
class DeviceResponse(BaseModel):
    id: str; hostname: str; device_type: Optional[str]; ip_address: Optional[str]
    os_version: Optional[str]; status: str; last_seen: Optional[datetime]
    class Config: from_attributes = True
@router.get("/", response_model=List[DeviceResponse])
async def get_devices(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Device))
    return result.scalars().all()
