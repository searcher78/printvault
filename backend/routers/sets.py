import os
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from database import get_session
from models import (FileSet, FileSetCreate, FileSetMember, FileSetMemberAdd,
                    FolderSet, FolderSetUpsert, PrintFile, PrintFileRead)

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


# ── FileSet endpoints ──────────────────────────────────────────────────────────

@router.get("/filesets")
def list_filesets(session: Session = Depends(get_session)):
    filesets = session.exec(select(FileSet)).all()
    result = []
    for s in filesets:
        members = session.exec(
            select(FileSetMember).where(FileSetMember.set_id == s.id)
        ).all()
        result.append({
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "file_count": len(members),
            "preview_ids": [m.file_id for m in members[:4]],
        })
    return result


@router.post("/filesets")
def create_fileset(body: FileSetCreate, session: Session = Depends(get_session)):
    s = FileSet(name=body.name, description=body.description)
    session.add(s)
    session.commit()
    session.refresh(s)
    return {"id": s.id, "name": s.name, "description": s.description,
            "file_count": 0, "preview_ids": []}


@router.put("/filesets/{set_id}")
def update_fileset(set_id: int, body: FileSetCreate,
                   session: Session = Depends(get_session)):
    s = session.get(FileSet, set_id)
    if not s:
        raise HTTPException(status_code=404, detail="FileSet not found")
    s.name = body.name
    s.description = body.description
    session.add(s)
    session.commit()
    return {"ok": True}


@router.delete("/filesets/{set_id}")
def delete_fileset(set_id: int, session: Session = Depends(get_session)):
    s = session.get(FileSet, set_id)
    if not s:
        raise HTTPException(status_code=404, detail="FileSet not found")
    for m in session.exec(
        select(FileSetMember).where(FileSetMember.set_id == set_id)
    ).all():
        session.delete(m)
    session.delete(s)
    session.commit()
    return {"ok": True}


@router.get("/filesets/{set_id}/files", response_model=list[PrintFileRead])
def get_fileset_files(set_id: int, session: Session = Depends(get_session)):
    if not session.get(FileSet, set_id):
        raise HTTPException(status_code=404, detail="FileSet not found")
    members = session.exec(
        select(FileSetMember).where(FileSetMember.set_id == set_id)
    ).all()
    files = [session.get(PrintFile, m.file_id) for m in members]
    return [PrintFileRead.from_db(f) for f in files if f]


@router.post("/filesets/{set_id}/members")
def add_to_fileset(set_id: int, body: FileSetMemberAdd,
                   session: Session = Depends(get_session)):
    if not session.get(FileSet, set_id):
        raise HTTPException(status_code=404, detail="FileSet not found")
    existing = session.exec(
        select(FileSetMember).where(
            FileSetMember.set_id == set_id,
            FileSetMember.file_id == body.file_id,
        )
    ).first()
    if not existing:
        session.add(FileSetMember(set_id=set_id, file_id=body.file_id))
        session.commit()
    return {"ok": True}


@router.delete("/filesets/{set_id}/members/{file_id}")
def remove_from_fileset(set_id: int, file_id: int,
                        session: Session = Depends(get_session)):
    member = session.exec(
        select(FileSetMember).where(
            FileSetMember.set_id == set_id,
            FileSetMember.file_id == file_id,
        )
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    session.delete(member)
    session.commit()
    return {"ok": True}


@router.get("/files/{file_id}/filesets")
def get_file_filesets(file_id: int, session: Session = Depends(get_session)):
    memberships = session.exec(
        select(FileSetMember).where(FileSetMember.file_id == file_id)
    ).all()
    sets = [session.get(FileSet, m.set_id) for m in memberships]
    return [{"id": s.id, "name": s.name} for s in sets if s]
