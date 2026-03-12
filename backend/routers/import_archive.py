import hashlib
import json
import logging
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import aiofiles
from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File
from sqlmodel import Session, select

from database import engine
from models import PrintFile
from services.archive import extract_archive, is_archive, SUPPORTED_3D

router = APIRouter()
logger = logging.getLogger(__name__)

IMPORT_DIR = os.getenv("IMPORT_DIR", "/app/data/imported")


def _compute_hash(path: str, chunk: int = 65536) -> str | None:
    try:
        h = hashlib.md5()
        with open(path, "rb") as f:
            while data := f.read(chunk):
                h.update(data)
        return h.hexdigest()
    except OSError:
        return None


def _unique_dest(base: Path, stem: str) -> Path:
    """Return a non-existing subdirectory path under base."""
    candidate = base / stem
    counter = 0
    while candidate.exists():
        counter += 1
        candidate = base / f"{stem}_{counter}"
    return candidate


def _process_new_files(new_ids: list[int]) -> None:
    """Thumbnail + AI für neu importierte Dateien (läuft als BackgroundTask)."""
    from services.scanner import _process_file
    for file_id in new_ids:
        try:
            _process_file(file_id)
        except Exception as e:
            logger.error("Fehler bei Verarbeitung id=%s: %s", file_id, e)


@router.post("/import")
async def import_archive(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    filename = file.filename or "upload"
    if not is_archive(filename):
        raise HTTPException(status_code=400, detail=f"Nicht unterstütztes Dateiformat: {Path(filename).suffix}")

    import_base = Path(IMPORT_DIR)
    import_base.mkdir(parents=True, exist_ok=True)

    # Archiv-Dateiname → Zielordnername (ohne Suffix(e))
    stem = Path(filename).stem
    if stem.endswith(".tar"):
        stem = stem[:-4]  # .tar.gz → ohne .tar

    dest_dir = _unique_dest(import_base, stem)

    # Hochgeladene Datei als temporäre Datei streamen
    suffix = Path(filename).suffix
    tmp_fd, tmp_path_str = tempfile.mkstemp(suffix=suffix, dir=import_base)
    tmp_path = Path(tmp_path_str)
    try:
        async with aiofiles.open(tmp_path, "wb") as out:
            while chunk := await file.read(1024 * 1024):  # 1 MB-Blöcke
                await out.write(chunk)
        os.close(tmp_fd)

        try:
            found_files = extract_archive(tmp_path, dest_dir)
        except Exception as e:
            shutil.rmtree(dest_dir, ignore_errors=True)
            raise HTTPException(status_code=422, detail=f"Entpacken fehlgeschlagen: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)

    if not found_files:
        shutil.rmtree(dest_dir, ignore_errors=True)
        return {"imported": 0, "skipped": 0, "errors": [],
                "message": "Keine 3D-Dateien im Archiv gefunden"}

    # Neue Dateien in DB registrieren
    imported = skipped = 0
    errors: list[str] = []
    new_ids: list[int] = []

    with Session(engine) as session:
        # Nach der Extraktion neu laden – Watcher kann Dateien bereits registriert haben
        session.expire_all()
        existing_paths = {f.path for f in session.exec(select(PrintFile)).all()}
        for path in found_files:
            str_path = str(path)
            if str_path in existing_paths:
                skipped += 1
                continue
            try:
                with session.begin_nested():  # Savepoint: Fehler rollt nur diesen Eintrag zurück
                    pf = PrintFile(
                        name=path.stem,
                        path=str_path,
                        format=SUPPORTED_3D.get(path.suffix.lower(), path.suffix[1:].upper()),
                        size_bytes=path.stat().st_size,
                        file_hash=_compute_hash(str_path),
                    )
                    session.add(pf)
                    session.flush()
                new_ids.append(pf.id)
                imported += 1
            except Exception as e:
                skipped += 1
                logger.warning("Übersprungen %s: %s", path.name, e)
        try:
            session.commit()
        except Exception as e:
            logger.error("DB-Commit fehlgeschlagen: %s", e)
            raise HTTPException(status_code=503, detail=f"Datenbankfehler beim Speichern: {e}")

    # Thumbnail-Rendering + AI im Hintergrund
    if new_ids:
        background_tasks.add_task(_process_new_files, new_ids)

    logger.info("Import '%s': %d importiert, %d übersprungen", filename, imported, skipped)
    return {"imported": imported, "skipped": skipped, "errors": errors}
