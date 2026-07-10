import mimetypes
import uuid
from collections.abc import Sequence
from pathlib import Path
from uuid import uuid7

import aiofiles
import aiofiles.os
from fastapi import UploadFile

from src.config import settings
from src.models import Alert, StoredFile
from src.repository import AlertRepository, FileRepository

# Размер чанка (кусочка) для чтения/записи файла (1 МБ)
CHUNK_SIZE = 1024 * 1024


class FileService:
    """Сервис для работы с файлами. Инкапсулирует всю бизнес-логику."""

    def __init__(self, file_repo: FileRepository) -> None:
        self.file_repo = file_repo

    async def list_files(self) -> Sequence[StoredFile]:
        """Получает список всех файлов."""
        return await self.file_repo.list_all()

    async def get_file(self, file_id: uuid.UUID) -> StoredFile:
        """Ищет файл по ID."""
        file_item = await self.file_repo.get_by_id(file_id)
        if not file_item:
            raise FileNotFoundError("File not found")
        return file_item

    async def create_file(self, title: str, upload_file: UploadFile) -> StoredFile:
        """Сохраняет загруженный файл чанками на диск и создает запись в БД."""
        file_id = uuid7()
        original_name = upload_file.filename or "unknown"
        suffix = Path(original_name).suffix
        stored_name = f"{file_id}{suffix}"
        stored_path = settings.storage_dir / stored_name

        size = 0
        async with aiofiles.open(stored_path, "wb") as buffer:
            while True:
                chunk = await upload_file.read(CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                await buffer.write(chunk)

        if size == 0:
            # Если файл оказался пуст, асинхронно удаляем
            try:
                await aiofiles.os.remove(stored_path)
            except FileNotFoundError:
                pass
            raise ValueError("File is empty")

        mime_type = (
                upload_file.content_type
                or mimetypes.guess_type(stored_name)[0]
                or "application/octet-stream"
        )

        file_item = StoredFile(
            id=file_id,
            title=title,
            original_name=original_name if original_name != "unknown" else stored_name,
            stored_name=stored_name,
            mime_type=mime_type,
            size=size,
            processing_status="uploaded",
        )
        return await self.file_repo.add(file_item)

    async def update_file(self, file_id: uuid.UUID, title: str) -> StoredFile:
        """Обновляет метаданные файла."""
        file_item = await self.get_file(file_id)
        file_item.title = title
        await self.file_repo.commit_changes()
        return file_item

    async def delete_file(self, file_id: uuid.UUID) -> None:
        """Удаляет файл с диска и из БД."""
        file_item = await self.get_file(file_id)
        stored_path = settings.storage_dir / file_item.stored_name

        # Асинхронное удаление
        try:
            await aiofiles.os.remove(stored_path)
        except FileNotFoundError:
            pass

        await self.file_repo.delete(file_item)

    async def get_file_path_for_download(self, file_id: uuid.UUID) -> tuple[StoredFile, Path]:
        """Возвращает метаданные файла и путь для скачивания."""
        file_item = await self.get_file(file_id)
        stored_path = settings.storage_dir / file_item.stored_name

        # Проверяем физическое наличие файла
        if not stored_path.exists():
            raise FileNotFoundError("Stored file not found on disk")

        return file_item, stored_path


class AlertService:
    """Сервис для работы с алертами."""

    def __init__(self, alert_repo: AlertRepository) -> None:
        self.alert_repo = alert_repo

    async def list_alerts(self) -> Sequence[Alert]:
        """Получает список всех алертов."""
        return await self.alert_repo.list_all()

    async def create_alert(self, file_id: uuid.UUID, level: str, message: str) -> Alert:
        """Создает новый алерт."""
        alert = Alert(file_id=file_id, level=level, message=message)
        return await self.alert_repo.add(alert)
