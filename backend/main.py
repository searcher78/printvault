import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from database import create_db_and_tables
from routers import files, rename, scan, settings
from services.watcher import start_watcher, stop_watcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s – %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    start_watcher()
    yield
    stop_watcher()


app = FastAPI(title="PrintVault", version="0.1.0", lifespan=lifespan)

app.include_router(files.router, prefix="/api")
app.include_router(rename.router, prefix="/api")
app.include_router(scan.router, prefix="/api")
app.include_router(settings.router, prefix="/api")

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse("static/index.html")
