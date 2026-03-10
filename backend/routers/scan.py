import threading

from fastapi import APIRouter

from services.scanner import run_scan, reprocess_thumbnails

router = APIRouter()


@router.post("/scan")
def trigger_scan():
    thread = threading.Thread(target=run_scan, daemon=True)
    thread.start()
    return {"status": "scan started"}


@router.post("/reprocess")
def trigger_reprocess():
    """Re-render all thumbnails (useful after renderer upgrade)."""
    thread = threading.Thread(target=reprocess_thumbnails, daemon=True)
    thread.start()
    return {"status": "reprocess started"}
