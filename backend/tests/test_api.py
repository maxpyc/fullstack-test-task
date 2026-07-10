import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from src.app import app, get_file_service
from src.models import StoredFile


# === Фикстуры данных ===

@pytest.fixture
def dummy_uuid() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def dummy_file_item(dummy_uuid: uuid.UUID) -> StoredFile:
    """Создает фейковый объект файла (как будто из БД)"""
    return StoredFile(
        id=dummy_uuid,
        title="Test Document",
        original_name="test.pdf",
        stored_name=f"{dummy_uuid}.pdf",
        mime_type="application/pdf",
        size=1024,
        processing_status="uploaded",
        scan_status="clean",
        scan_details="no threats found",
        metadata_json={"approx_page_count": 5},
        requires_attention=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


# === Мок-сервисы ===

class MockFileService:
    """Мок-сервис, который имитирует работу реального FileService без БД и диска."""

    def __init__(self, dummy_file: StoredFile) -> None:
        self.dummy_file = dummy_file

    async def list_files(self) -> list[StoredFile]:
        return [self.dummy_file]

    async def get_file(self, file_id: uuid.UUID) -> StoredFile:
        if file_id == self.dummy_file.id:
            return self.dummy_file
        raise FileNotFoundError("File not found")

    async def create_file(self, title: str, upload_file: MagicMock) -> StoredFile:
        return self.dummy_file

    async def update_file(self, file_id: uuid.UUID, title: str) -> StoredFile:
        if file_id == self.dummy_file.id:
            self.dummy_file.title = title
            return self.dummy_file
        raise FileNotFoundError("File not found")

    async def delete_file(self, file_id: uuid.UUID) -> None:
        if file_id != self.dummy_file.id:
            raise FileNotFoundError("File not found")

    async def get_file_path_for_download(self, file_id: uuid.UUID) -> tuple[StoredFile, Path]:
        if file_id == self.dummy_file.id:
            # Возвращаем путь к текущему файлу тестов просто чтобы FileResponse не упал
            return self.dummy_file, Path(__file__)
        raise FileNotFoundError("File not found")


# === Фикстура HTTP-клиента с переопределением зависимостей ===

@pytest.fixture
async def client(dummy_file_item: StoredFile):
    """
    Создает тестовый HTTP-клиент, подменяя реальный сервис на мок.
    Все запросы в этом клиенте не будут трогать БД.
    """
    mock_service = MockFileService(dummy_file_item)
    app.dependency_overrides[get_file_service] = lambda: mock_service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Очищаем переопределения после теста
    app.dependency_overrides.clear()


# === Тесты Эндпоинтов ===

async def test_list_files(client: AsyncClient, dummy_file_item: StoredFile) -> None:
    response = await client.get("/files")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["id"] == str(dummy_file_item.id)
    assert data[0]["title"] == "Test Document"


@patch("src.app.scan_file_for_threats.delay")  # Мокаем вызов Celery, чтобы не лезть в Redis
async def test_create_file(mock_celery_task: MagicMock, client: AsyncClient,
                           dummy_file_item: StoredFile) -> None:
    # Имитируем отправку multipart/form-data
    response = await client.post(
        "/files",
        data={"title": "New Upload"},
        files={"file": ("test.pdf", b"dummy content", "application/pdf")},
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["id"] == str(dummy_file_item.id)

    # Проверяем, что роутер действительно попытался отправить задачу в фоновый воркер
    mock_celery_task.assert_called_once_with(str(dummy_file_item.id))


async def test_get_file_success(client: AsyncClient, dummy_file_item: StoredFile) -> None:
    response = await client.get(f"/files/{dummy_file_item.id}")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["original_name"] == "test.pdf"


async def test_get_file_not_found(client: AsyncClient) -> None:
    random_uuid = uuid.uuid4()
    response = await client.get(f"/files/{random_uuid}")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["detail"] == "File not found"


async def test_update_file(client: AsyncClient, dummy_file_item: StoredFile) -> None:
    payload = {"title": "Updated Title"}
    response = await client.patch(f"/files/{dummy_file_item.id}", json=payload)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["title"] == "Updated Title"


async def test_delete_file_success(client: AsyncClient, dummy_file_item: StoredFile) -> None:
    response = await client.delete(f"/files/{dummy_file_item.id}")
    assert response.status_code == status.HTTP_204_NO_CONTENT
