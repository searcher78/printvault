import json
import os
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from database import get_session
from models import PrintFile, PrintFileRead, PrintFileUpdate

router = APIRouter()

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_PRIORITY_STEMS = {"preview", "cover", "thumbnail", "render", "foto", "photo",
                   "bild", "fertig", "finished", "result"}


def _find_folder_image(folder_abs: str) -> bool:
    """Return True if the folder contains at least one image file."""
    try:
        return any(
            os.path.splitext(e)[1].lower() in _IMAGE_EXTS
            for e in os.listdir(folder_abs)
            if os.path.isfile(os.path.join(folder_abs, e))
        )
    except OSError:
        return False


def _get_folder_image_path(folder_abs: str) -> str | None:
    """Return the path of the best image in the folder, or None."""
    try:
        entries = os.listdir(folder_abs)
    except OSError:
        return None
    images = sorted(
        e for e in entries
        if os.path.splitext(e)[1].lower() in _IMAGE_EXTS
        and os.path.isfile(os.path.join(folder_abs, e))
    )
    if not images:
        return None
    for img in images:
        if os.path.splitext(img)[0].lower() in _PRIORITY_STEMS:
            return os.path.join(folder_abs, img)
    return os.path.join(folder_abs, images[0])


@router.get("/folders")
def get_folders(session: Session = Depends(get_session)):
    """Return all folders that contain files, with file counts and preview IDs."""
    files_dir = os.getenv("FILES_DIR", "/files")
    all_files = session.exec(select(PrintFile)).all()
    folders: dict = defaultdict(lambda: {"count": 0, "preview_ids": []})
    for f in all_files:
        try:
            rel = os.path.relpath(os.path.dirname(f.path), files_dir)
            if rel == ".":
                continue
        except ValueError:
            continue
        folders[rel]["count"] += 1
        if len(folders[rel]["preview_ids"]) < 4:
            folders[rel]["preview_ids"].append(f.id)
    return [
        {
            "folder": k,
            "display": os.path.basename(k) or k,
            "count": v["count"],
            "preview_ids": v["preview_ids"],
            "has_image": _find_folder_image(os.path.join(files_dir, k)),
        }
        for k, v in sorted(folders.items())
    ]


@router.get("/folder-image")
def get_folder_image(folder: str):
    """Serve the preview image found in the given folder (relative path)."""
    files_dir = os.getenv("FILES_DIR", "/files")
    folder_abs = os.path.normpath(os.path.join(files_dir, folder))
    # Security: must stay within files_dir
    if not folder_abs.startswith(os.path.normpath(files_dir)):
        raise HTTPException(status_code=400, detail="Invalid folder path")
    img_path = _get_folder_image_path(folder_abs)
    if not img_path:
        raise HTTPException(status_code=404, detail="No image found in folder")
    ext = os.path.splitext(img_path)[1].lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "webp": "image/webp", "gif": "image/gif"}.get(ext, "image/jpeg")
    return FileResponse(img_path, media_type=mime)


@router.get("/files", response_model=list[PrintFileRead])
def list_files(
    search: Optional[str] = None,
    category: Optional[str] = None,
    format: Optional[str] = None,
    favorite: Optional[bool] = None,
    status: Optional[str] = None,
    folder: Optional[str] = None,
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
    if folder:
        files_dir = os.getenv("FILES_DIR", "/files")
        folder_abs = os.path.join(files_dir, folder)
        query = query.where(PrintFile.path.like(folder_abs + "/%"))

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
