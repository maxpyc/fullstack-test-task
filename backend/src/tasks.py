import asyncio
import uuid
from pathlib import Path

from celery import Celery
from celery.signals import worker_process_init

from src.config import settings
from src.database import async_session_maker, engine
from src.models import Alert
from src.repository import AlertRepository, FileRepository

celery_app = Celery(
    "file_tasks",
    broker=settings.celery_broker_url,
    backend=settings.celery_broker_url,
)

_loop: asyncio.AbstractEventLoop | None = None


def run_async(coro):
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop.run_until_complete(coro)


@worker_process_init.connect
def bootstrap_worker_db_pool(*args, **kwargs) -> None:
    """Сбрасываем пул при форке процесса воркера."""
    try:
        engine.sync_engine.dispose()
    except Exception as e:
        print(f"[Celery Worker Init] Safe pool dispose skipped: {e}")


async def _scan_file_for_threats(file_id_str: str) -> None:
    file_id = uuid.UUID(file_id_str)

    async with async_session_maker() as session:
        repo = FileRepository(session)
        file_item = await repo.get_by_id(file_id)
        if not file_item:
            return

        file_item.processing_status = "processing"
        reasons: list[str] = []
        extension = Path(file_item.original_name).suffix.lower()

        if extension in {".exe", ".bat", ".cmd", ".sh", ".js"}:
            reasons.append(f"suspicious extension {extension}")

        if file_item.size > 10 * 1024 * 1024:
            reasons.append("file is larger than 10 MB")

        if extension == ".pdf" and file_item.mime_type not in {
            "application/pdf",
            "application/octet-stream",
        }:
            reasons.append("pdf extension does not match mime type")

        file_item.scan_status = "suspicious" if reasons else "clean"
        file_item.scan_details = ", ".join(reasons) if reasons else "no threats found"
        file_item.requires_attention = bool(reasons)
        await repo.commit_changes()

    extract_file_metadata.delay(file_id_str)


async def _extract_file_metadata(file_id_str: str) -> None:
    file_id = uuid.UUID(file_id_str)

    async with async_session_maker() as session:
        repo = FileRepository(session)
        file_item = await repo.get_by_id(file_id)
        if not file_item:
            return

        stored_path = settings.storage_dir / file_item.stored_name
        if not stored_path.exists():
            file_item.processing_status = "failed"
            file_item.scan_status = file_item.scan_status or "failed"
            file_item.scan_details = "stored file not found during metadata extraction"
            await repo.commit_changes()
            send_file_alert.delay(file_id_str)
            return

        metadata = {
            "extension": Path(file_item.original_name).suffix.lower(),
            "size_bytes": file_item.size,
            "mime_type": file_item.mime_type,
        }

        if file_item.mime_type.startswith("text/"):
            line_count = 0
            char_count = 0
            with stored_path.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line_count += 1
                    char_count += len(line)
            metadata["line_count"] = line_count
            metadata["char_count"] = char_count

        elif file_item.mime_type == "application/pdf":
            target = b"/Type /Page"
            overlap = len(target) - 1
            page_count = 0
            buffer = b""

            with stored_path.open("rb") as f:
                while chunk := f.read(1024 * 1024):
                    buffer += chunk
                    page_count += buffer.count(target)
                    if len(buffer) >= overlap:
                        buffer = buffer[-overlap:]

            metadata["approx_page_count"] = max(page_count, 1)

        file_item.metadata_json = metadata
        file_item.processing_status = "processed"
        await repo.commit_changes()

    send_file_alert.delay(file_id_str)


async def _send_file_alert(file_id_str: str) -> None:
    file_id = uuid.UUID(file_id_str)

    async with async_session_maker() as session:
        file_repo = FileRepository(session)
        alert_repo = AlertRepository(session)

        file_item = await file_repo.get_by_id(file_id)
        if not file_item:
            return

        if file_item.processing_status == "failed":
            level, message = "critical", "File processing failed"
        elif file_item.requires_attention:
            level, message = "warning", f"File requires attention: {file_item.scan_details}"
        else:
            level, message = "info", "File processed successfully"

        alert = Alert(file_id=file_id, level=level, message=message)
        await alert_repo.add(alert)


@celery_app.task
def scan_file_for_threats(file_id: str) -> None:
    run_async(_scan_file_for_threats(file_id))


@celery_app.task
def extract_file_metadata(file_id: str) -> None:
    run_async(_extract_file_metadata(file_id))


@celery_app.task
def send_file_alert(file_id: str) -> None:
    run_async(_send_file_alert(file_id))
