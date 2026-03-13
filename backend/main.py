import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from database import create_db_and_tables
from routers import files, import_archive, locate, rename, scan, settings, sets
from services.watcher import start_watcher, stop_watcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s – %(message)s",
)

logger = logging.getLogger(__name__)


def _resume_pending() -> None:
    """Nach Container-Neustart unterbrochene Verarbeitung fortsetzen.

    Wenn der Container während des Thumbnail-Renderings neu gestartet wird,
    bleiben Dateien mit thumbnail_path=None in der DB. Diese Funktion holt
    das Rendering (und anschließend das KI-Tagging) für alle solchen Dateien
    nach. Läuft als Daemon-Thread, blockiert den Server-Start nicht.
    """
    from sqlmodel import Session, select
    from database import engine
    from models import PrintFile
    from services.scanner import _process_file

    with Session(engine) as session:
        pending = session.exec(
            select(PrintFile).where(PrintFile.thumbnail_path == None)
        ).all()
        ids = [f.id for f in pending]

    if not ids:
        return

    logger.info("Startup: %d Dateien ohne Thumbnail – starte Nachverarbeitung", len(ids))
    for file_id in ids:
        _process_file(file_id)
    logger.info("Startup-Nachverarbeitung abgeschlossen")


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    start_watcher()
    threading.Thread(target=_resume_pending, daemon=True).start()
    yield
    stop_watcher()


app = FastAPI(title="PrintVault", version="0.1.0", lifespan=lifespan)

app.include_router(files.router, prefix="/api")
app.include_router(import_archive.router, prefix="/api")
app.include_router(locate.router, prefix="/api")
app.include_router(rename.router, prefix="/api")
app.include_router(scan.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(sets.router, prefix="/api")

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse("static/index.html")
