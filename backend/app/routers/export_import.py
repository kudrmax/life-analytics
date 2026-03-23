"""Export and import data in ZIP format (metrics + entries)."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse

from app.database import get_db
from app.auth import get_current_user
from app.repositories.export_repository import ExportRepository
from app.repositories.import_repository import ImportRepository
from app.services.export_service import ExportService
from app.services.import_service import ImportService

router = APIRouter(prefix="/api/export", tags=["export"])


@router.get("/csv")
async def export_data(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    service = ExportService(ExportRepository(db, current_user["id"]), db)
    zip_buffer = await service.export_zip()
    filename = f"life_analytics_{current_user['username']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    return StreamingResponse(
        iter([zip_buffer.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/import")
async def import_data(
    file: UploadFile = File(...),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if not file.filename.endswith('.zip'):
        raise HTTPException(400, "File must be a ZIP archive")
    content = await file.read()
    service = ImportService(ImportRepository(db, current_user["id"]), db)
    return await service.import_zip(content)
