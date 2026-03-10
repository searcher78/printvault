import json
import logging
import os
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from database import engine
from models import PrintFile

logger = logging.getLogger(__name__)

SUPPORTED_FORMATS = {".stl": "STL", ".3mf": "3MF", ".obj": "OBJ", ".lys": "LYS"}
FILES_DIR = os.getenv("FILES_DIR", "/files")


def run_scan() -> None:
    """Scan FILES_DIR for new 3D print files, generate thumbnails and AI-tag them."""
    logger.info(f"Scan started: {FILES_DIR}")
    files_dir = Path(FILES_DIR)
    if not files_dir.exists():
        logger.warning(f"Files directory does not exist: {FILES_DIR}")
        return

    new_ids: list[int] = []

    with Session(engine) as session:
        existing_paths = {f.path for f in session.exec(select(PrintFile)).all()}

        for path in files_dir.rglob("*"):
            if path.suffix.lower() not in SUPPORTED_FORMATS:
                continue
            str_path = str(path)
            if str_path in existing_paths:
                continue

            file = PrintFile(
                name=path.stem,
                path=str_path,
                format=SUPPORTED_FORMATS[path.suffix.lower()],
                size_bytes=path.stat().st_size,
            )
            session.add(file)
            session.flush()  # get auto-assigned id
            new_ids.append(file.id)

        session.commit()

    logger.info(f"Scan: {len(new_ids)} new files found")

    for file_id in new_ids:
        _process_file(file_id)

    _retry_ai_unprocessed()


def _process_file(file_id: int) -> None:
    """Render thumbnail then run AI tagging for a single file."""
    from services.thumbnail import generate_thumbnail
    from services.ai_tagger import tag_file

    with Session(engine) as session:
        file = session.get(PrintFile, file_id)
        if not file:
            return

        thumbnail_path = generate_thumbnail(file.path, file_id)
        if thumbnail_path:
            file.thumbnail_path = thumbnail_path
            session.add(file)
            session.commit()
            session.refresh(file)

        if not file.ai_processed and thumbnail_path:
            result = tag_file(file.path, thumbnail_path)
            if result:
                file.category = result.get("category", "misc")
                file.tags = json.dumps(result.get("tags", []))
                file.supports_needed = bool(result.get("supports_needed", False))
                file.difficulty = result.get("difficulty", "medium")
                file.notes = result.get("notes", "")
                file.ai_processed = True
                file.date_modified = datetime.utcnow()
                session.add(file)
                session.commit()


def _retry_ai_unprocessed() -> None:
    """Retry AI tagging for files that have a thumbnail but aren't tagged yet."""
    with Session(engine) as session:
        pending = session.exec(
            select(PrintFile).where(
                PrintFile.ai_processed == False,
                PrintFile.thumbnail_path != None,
            )
        ).all()
        ids = [f.id for f in pending]

    for file_id in ids:
        logger.info(f"Retrying AI tag for file id={file_id}")
        _process_file(file_id)
