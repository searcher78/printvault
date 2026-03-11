import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_session
from models import PrintFile, PrintFileRead

router = APIRouter()


class RenameFileRequest(BaseModel):
    new_name: str


class RenameFolderRequest(BaseModel):
    folder: str   # relative path within FILES_DIR
    new_name: str  # new folder name (last component only, no slashes)


@router.post("/files/{file_id}/rename", response_model=PrintFileRead)
def rename_file(
    file_id: int,
    body: RenameFileRequest,
    session: Session = Depends(get_session),
):
    file = session.get(PrintFile, file_id)
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    new_name = body.new_name.strip().replace("/", "").replace("\\", "")
    if not new_name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")

    old_path = file.path
    ext = os.path.splitext(old_path)[1]
    new_path = os.path.join(os.path.dirname(old_path), new_name + ext)

    if new_path == old_path:
        return PrintFileRead.from_db(file)

    if not os.path.exists(old_path):
        raise HTTPException(status_code=404, detail="Physical file not found")
    if os.path.exists(new_path):
        raise HTTPException(status_code=409, detail="A file with that name already exists")

    os.rename(old_path, new_path)

    file.name = new_name
    file.path = new_path
    file.date_modified = datetime.utcnow()
    session.add(file)
    session.commit()
    session.refresh(file)
    return PrintFileRead.from_db(file)


@router.post("/folders/rename")
def rename_folder(
    body: RenameFolderRequest,
    session: Session = Depends(get_session),
):
    files_dir = os.getenv("FILES_DIR", "/files")

    old_rel = body.folder.strip("/")
    new_name = body.new_name.strip().replace("/", "").replace("\\", "")
    if not new_name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")

    old_abs = os.path.join(files_dir, old_rel)
    if not os.path.isdir(old_abs):
        raise HTTPException(status_code=404, detail="Folder not found")

    parent_abs = os.path.dirname(old_abs)
    new_abs = os.path.join(parent_abs, new_name)
    new_rel = os.path.relpath(new_abs, files_dir)

    if new_abs == old_abs:
        return {"folder": old_rel, "new_folder": new_rel}
    if os.path.exists(new_abs):
        raise HTTPException(status_code=409, detail="A folder with that name already exists")

    os.rename(old_abs, new_abs)

    # Update all DB paths under the old folder
    all_files = session.exec(select(PrintFile)).all()
    old_prefix = old_abs.rstrip("/") + "/"
    new_prefix = new_abs.rstrip("/") + "/"
    for f in all_files:
        if f.path.startswith(old_prefix):
            f.path = new_prefix + f.path[len(old_prefix):]
            session.add(f)
    session.commit()

    return {"folder": old_rel, "new_folder": new_rel}
