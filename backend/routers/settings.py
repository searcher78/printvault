from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from database import get_session
from models import Settings

router = APIRouter()

DEFAULT_SETTINGS: dict[str, str] = {
    "files_dir": "/files",
    "ollama_base_url": "http://localhost:11434",
    "ollama_model": "qwen2.5vl:7b",
    "thumbnail_dir": "/app/data/thumbnails",
    "auto_scan": "true",
}


@router.get("/settings")
def get_settings(session: Session = Depends(get_session)):
    rows = session.exec(select(Settings)).all()
    result = dict(DEFAULT_SETTINGS)
    for row in rows:
        result[row.key] = row.value
    return result


@router.put("/settings")
def update_settings(data: dict, session: Session = Depends(get_session)):
    for key, value in data.items():
        row = session.exec(select(Settings).where(Settings.key == key)).first()
        if row:
            row.value = str(value)
        else:
            row = Settings(key=key, value=str(value))
        session.add(row)
    session.commit()
    return get_settings(session)
