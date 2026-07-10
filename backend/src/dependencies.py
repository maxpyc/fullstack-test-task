from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.repository import FileRepository, AlertRepository
from src.service import FileService, AlertService


def get_file_service(session: AsyncSession = Depends(get_session)) -> FileService:
    return FileService(FileRepository(session))


def get_alert_service(session: AsyncSession = Depends(get_session)) -> AlertService:
    return AlertService(AlertRepository(session))
