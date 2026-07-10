from uuid import UUID

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from src.dependencies import get_file_service, get_alert_service
from src.schemas import AlertItem, FileItem, FileUpdate
from src.service import AlertService, FileService
from src.tasks import scan_file_for_threats

app = FastAPI(title="File Sharing Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/files", response_model=list[FileItem])
async def list_files_view(service: FileService = Depends(get_file_service)):
    return await service.list_files()


@app.get("/alerts", response_model=list[AlertItem])
async def list_alerts_view(service: AlertService = Depends(get_alert_service)):
    return await service.list_alerts()


@app.post("/files", response_model=FileItem, status_code=status.HTTP_201_CREATED)
async def create_file_view(
        title: str = Form(...),
        file: UploadFile = File(...),
        service: FileService = Depends(get_file_service)
):
    try:
        file_item = await service.create_file(title=title, upload_file=file)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Фоновая задача уходит в Celery
    scan_file_for_threats.delay(str(file_item.id))
    return file_item


@app.get("/files/{file_id}", response_model=FileItem)
async def get_file_view(
        file_id: UUID,
        service: FileService = Depends(get_file_service)
):
    try:
        return await service.get_file(file_id)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")


@app.patch("/files/{file_id}", response_model=FileItem)
async def update_file_view(
        file_id: UUID,
        payload: FileUpdate,
        service: FileService = Depends(get_file_service)
):
    try:
        return await service.update_file(file_id=file_id, title=payload.title)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")


@app.get("/files/{file_id}/download")
async def download_file(
        file_id: UUID,
        service: FileService = Depends(get_file_service)
):
    try:
        file_item, stored_path = await service.get_file_path_for_download(file_id)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stored file not found")

    return FileResponse(
        path=stored_path,
        media_type=file_item.mime_type,
        filename=file_item.original_name,
    )


@app.delete("/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file_view(
        file_id: UUID,
        service: FileService = Depends(get_file_service)
):
    try:
        await service.delete_file(file_id)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
