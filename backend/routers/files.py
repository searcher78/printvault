import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from database import get_session
from models import PrintFile, PrintFileRead, PrintFileUpdate

router = APIRouter()


@router.get("/files", response_model=list[PrintFileRead])
def list_files(
    search: Optional[str] = None,
    category: Optional[str] = None,
    format: Optional[str] = None,
    favorite: Optional[bool] = None,
    status: Optional[str] = None,
    sort: str = "date",
    order: str = "desc",
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    session: Session = Depends(get_session),
):
    query = select(PrintFile)

    if search:
        query = query.where(
            (PrintFile.name.ilike(f"%{search}%"))
            | (PrintFile.tags.ilike(f"%{search}%"))
        )
    if category:
        query = query.where(PrintFile.category == category)
    if format:
        query = query.where(PrintFile.format == format.upper())
    if favorite is not None:
        query = query.where(PrintFile.favorite == favorite)
    if status:
        query = query.where(PrintFile.print_status == status)

    sort_col = {
        "date": PrintFile.date_added,
        "name": PrintFile.name,
        "size": PrintFile.size_bytes,
    }.get(sort, PrintFile.date_added)

    query = query.order_by(sort_col.asc() if order == "asc" else sort_col.desc())
    query = query.offset(offset).limit(limit)

    return [PrintFileRead.from_db(f) for f in session.exec(query).all()]


@router.get("/files/{file_id}", response_model=PrintFileRead)
def get_file(file_id: int, session: Session = Depends(get_session)):
    file = session.get(PrintFile, file_id)
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    return PrintFileRead.from_db(file)


@router.put("/files/{file_id}", response_model=PrintFileRead)
def update_file(
    file_id: int,
    update: PrintFileUpdate,
    session: Session = Depends(get_session),
):
    file = session.get(PrintFile, file_id)
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    update_data = update.model_dump(exclude_unset=True)
    if "tags" in update_data:
        update_data["tags"] = json.dumps(update_data["tags"])

    for key, value in update_data.items():
        setattr(file, key, value)

    from datetime import datetime
    file.date_modified = datetime.utcnow()

    session.add(file)
    session.commit()
    session.refresh(file)
    return PrintFileRead.from_db(file)


@router.get("/files/{file_id}/download")
def download_file(file_id: int, session: Session = Depends(get_session)):
    file = session.get(PrintFile, file_id)
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    if not os.path.exists(file.path):
        raise HTTPException(status_code=404, detail="Physical file not found")
    return FileResponse(
        file.path,
        filename=f"{file.name}.{file.format.lower()}",
        media_type="application/octet-stream",
    )


@router.get("/thumbnails/{file_id}")
def get_thumbnail(file_id: int, session: Session = Depends(get_session)):
    file = session.get(PrintFile, file_id)
    if not file or not file.thumbnail_path:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    if not os.path.exists(file.thumbnail_path):
        raise HTTPException(status_code=404, detail="Thumbnail file not found")
    return FileResponse(file.thumbnail_path, media_type="image/png")


@router.get("/stats")
def get_stats(session: Session = Depends(get_session)):
    files = session.exec(select(PrintFile)).all()
    categories: dict[str, int] = {}
    formats: dict[str, int] = {}
    for f in files:
        categories[f.category] = categories.get(f.category, 0) + 1
        formats[f.format] = formats.get(f.format, 0) + 1

    return {
        "total_files": len(files),
        "total_size_bytes": sum(f.size_bytes for f in files),
        "categories": categories,
        "formats": formats,
        "ai_processed": sum(1 for f in files if f.ai_processed),
        "favorites": sum(1 for f in files if f.favorite),
        "printed": sum(1 for f in files if f.print_status == "printed"),
    }
