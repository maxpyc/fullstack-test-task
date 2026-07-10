from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FileBase(BaseModel):
    title: str = Field(..., max_length=255)


class FileUpdate(FileBase):
    pass


class FileItem(FileBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    original_name: str
    mime_type: str
    size: int
    processing_status: str
    scan_status: str | None = None
    scan_details: str | None = None
    metadata_json: dict | None = None
    requires_attention: bool
    created_at: datetime
    updated_at: datetime


class AlertItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_id: UUID
    level: str
    message: str
    created_at: datetime