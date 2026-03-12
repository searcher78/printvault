import os
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from database import get_session
from models import FolderSet, FolderSetUpsert, PrintFile

router = APIRouter()


def _folder_counts(session: Session) -> dict[str, int]:
    """Return file count per folder (relative path)."""
    files_dir = os.getenv("FILES_DIR", "/files")
    counts: dict[str, int] = defaultdict(int)
    for f in session.exec(select(PrintFile)).all():
        try:
            rel = os.path.relpath(os.path.dirname(f.path), files_dir)
            if rel != ".":
                counts[rel] += 1
        except ValueError:
            pass
    return counts


@router.get("/sets")
def list_sets(session: Session = Depends(get_session)):
    sets = session.exec(select(FolderSet)).all()
    counts = _folder_counts(session)
    result = []
    for s in sets:
        # count files in this folder and all subfolders
        prefix = s.folder.rstrip("/") + "/"
        count = sum(
            c for f, c in counts.items()
            if f == s.folder or f.startswith(prefix)
        )
        result.append({
            "id": s.id,
            "folder": s.folder,
            "display_name": s.display_name or s.folder.split("/")[-1],
            "description": s.description,
            "file_count": count,
        })
    return result


@router.get("/sets/by-folder")
def get_set_by_folder(folder: str, session: Session = Depends(get_session)):
    s = session.exec(select(FolderSet).where(FolderSet.folder == folder)).first()
    if not s:
        raise HTTPException(status_code=404, detail="Set not found")
    return {
        "id": s.id,
        "folder": s.folder,
        "display_name": s.display_name,
        "description": s.description,
    }


@router.put("/sets")
def upsert_set(body: FolderSetUpsert, session: Session = Depends(get_session)):
    existing = session.exec(
        select(FolderSet).where(FolderSet.folder == body.folder)
    ).first()
    if existing:
        existing.display_name = body.display_name
        existing.description = body.description
        session.add(existing)
    else:
        session.add(FolderSet(
            folder=body.folder,
            display_name=body.display_name,
            description=body.description,
        ))
    session.commit()
    return {"ok": True}


@router.delete("/sets/{set_id}")
def delete_set(set_id: int, session: Session = Depends(get_session)):
    s = session.get(FolderSet, set_id)
    if not s:
        raise HTTPException(status_code=404, detail="Set not found")
    session.delete(s)
    session.commit()
    return {"ok": True}
