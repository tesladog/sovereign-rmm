from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_db
from models import Device

router = APIRouter()

class DeviceResponse(BaseModel):
    id: str
    hostname: str
    device_type: Optional[str] = None
    ip_address: Optional[str] = None
    os_version: Optional[str] = None
    status: str
    last_seen: Optional[datetime] = None
    
    class Config:
        from_attributes = True

@router.get("/", response_model=List[DeviceResponse])
async def get_devices(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Device))
    return result.scalars().all()

@router.post("/")
async def create_device(db: AsyncSession = Depends(get_db)):
    return {"message": "Device creation endpoint"}
