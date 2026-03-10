import threading

from fastapi import APIRouter

from services.scanner import run_scan

router = APIRouter()


@router.post("/scan")
def trigger_scan():
    thread = threading.Thread(target=run_scan, daemon=True)
    thread.start()
    return {"status": "scan started"}
