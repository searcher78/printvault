import base64
import json
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5vl:7b")

_PROMPT = """\
Du bist ein Assistent für 3D-Druck-Dateiverwaltung.
Analysiere dieses Vorschaubild einer 3D-Druckdatei und den Dateipfad.

Dateipfad: {file_path}

Antworte NUR mit einem JSON-Objekt (kein Markdown, kein Text darum):
{{
  "category": "miniatures|tools|deco|tech|cosplay|misc",
  "tags": ["tag1", "tag2", "tag3"],
  "supports_needed": true|false,
  "difficulty": "easy|medium|hard",
  "notes": "Kurze Beschreibung auf Deutsch, max 100 Zeichen"
}}\
"""

_VALID_CATEGORIES = {"miniatures", "tools", "deco", "tech", "cosplay", "misc"}
_VALID_DIFFICULTIES = {"easy", "medium", "hard"}


def tag_file(file_path: str, thumbnail_path: str) -> Optional[dict]:
    """Send thumbnail + path to Ollama and return parsed result dict, or None on error."""
    try:
        with open(thumbnail_path, "rb") as fh:
            image_b64 = base64.b64encode(fh.read()).decode()

        payload = {
            "model": OLLAMA_MODEL,
            "prompt": _PROMPT.format(file_path=file_path),
            "images": [image_b64],
            "stream": False,
        }

        with httpx.Client(timeout=60.0) as client:
            resp = client.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload)
            resp.raise_for_status()

        raw = resp.json().get("response", "")
        return _parse(raw)

    except Exception as exc:
        logger.error(f"AI tagging failed for {file_path}: {exc}")
        return None


def _parse(raw: str) -> Optional[dict]:
    raw = raw.strip()
    # Strip optional markdown code fences
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(f"Could not parse AI JSON response: {raw[:300]}")
        return None

    category = data.get("category", "misc")
    difficulty = data.get("difficulty", "medium")

    return {
        "category": category if category in _VALID_CATEGORIES else "misc",
        "tags": [str(t) for t in data.get("tags", [])][:10],
        "supports_needed": bool(data.get("supports_needed", False)),
        "difficulty": difficulty if difficulty in _VALID_DIFFICULTIES else "medium",
        "notes": str(data.get("notes", ""))[:100],
    }
