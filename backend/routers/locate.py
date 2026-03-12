import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_session
from models import PrintFile, PrintFileRead
from services.scanner import check_missing, compute_hash

router = APIRouter()

SUPPORTED_EXTS = {".stl", ".3mf", ".obj", ".lys"}


class RelinkRequest(BaseModel):
    new_path: str


def _path_similarity(original: str, candidate: str) -> int:
    """Count shared path components — higher = more similar location."""
    a = set(original.replace("\\", "/").split("/"))
    b = set(candidate.replace("\\", "/").split("/"))
    return len(a & b)


@router.post("/scan/check-missing")
def trigger_check_missing():
    """Validate all DB file paths and update the missing flag."""
    result = check_missing()
    return result


@router.get("/files/{file_id}/locate")
def locate_file(file_id: int, session: Session = Depends(get_session)):
    """
    Search FILES_DIR for the missing file.
    Strategy:
      1. Name match among unindexed files (fast)
      2. If no name match: hash match among unindexed files (thorough)
    Returns a ranked list of candidate paths.
    """
    file = session.get(PrintFile, file_id)
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    files_dir = os.getenv("FILES_DIR", "/files")
    if not os.path.isdir(files_dir):
        raise HTTPException(status_code=503, detail="FILES_DIR not accessible")

    known_paths = {f.path for f in session.exec(select(PrintFile)).all()}
    target_filename = os.path.basename(file.path).lower()
    target_hash = file.file_hash

    name_matches: list[str] = []
    hash_matches: list[str] = []

    for root, _dirs, fnames in os.walk(files_dir):
        for fname in fnames:
            if os.path.splitext(fname)[1].lower() not in SUPPORTED_EXTS:
                continue
            fpath = os.path.join(root, fname)
            if fpath in known_paths:
                continue  # already indexed, skip

            if fname.lower() == target_filename:
                name_matches.append(fpath)
            elif target_hash and not name_matches:
                # only hash-scan when no name match found yet (performance)
                h = compute_hash(fpath)
                if h and h == target_hash:
                    hash_matches.append(fpath)

    # If we found name matches but still want hash matches for renames,
    # do a second pass only if name_matches is empty
    candidates = (
        sorted(name_matches, key=lambda p: _path_similarity(file.path, p), reverse=True)
        + sorted(hash_matches, key=lambda p: _path_similarity(file.path, p), reverse=True)
    )

    return {
        "original_path": file.path,
        "candidates": [
            {
                "path": p,
                "match_type": "name" if p in name_matches else "hash",
                "similarity": _path_similarity(file.path, p),
            }
            for p in candidates
        ],
    }


@router.post("/files/{file_id}/relink", response_model=PrintFileRead)
def relink_file(
    file_id: int,
    body: RelinkRequest,
    session: Session = Depends(get_session),
):
    """Update a file's path in the DB after it was moved/renamed externally."""
    file = session.get(PrintFile, file_id)
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    new_path = body.new_path
    if not os.path.exists(new_path):
        raise HTTPException(status_code=404, detail="New path does not exist on disk")

    # Check no other DB entry already uses this path
    existing = session.exec(select(PrintFile).where(PrintFile.path == new_path)).first()
    if existing and existing.id != file_id:
        raise HTTPException(status_code=409, detail="Path already used by another file")

    files_dir = os.getenv("FILES_DIR", "/files")
    if not new_path.startswith(files_dir):
        raise HTTPException(status_code=400, detail="Path outside FILES_DIR")

    file.path = new_path
    file.missing = False
    file.file_hash = compute_hash(new_path)
    file.date_modified = datetime.utcnow()
    session.add(file)
    session.commit()
    session.refresh(file)
    return PrintFileRead.from_db(file)
