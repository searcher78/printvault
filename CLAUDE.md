# PrintVault – 3D Print File Manager

## Projektübersicht
Selbst gehosteter 3D-Druck-Dateimanager für Unraid.
Scannt ein lokales Verzeichnis mit STL/3MF/OBJ-Dateien, generiert Vorschaubilder,
kategorisiert Dateien automatisch per KI (Qwen2.5-VL via Ollama) und stellt
eine Weboberfläche zum Suchen, Filtern und Herunterladen bereit.

## UI-Referenz
- Prototyp liegt unter `/ui/3d-print-manager.html`
- Farben, Layout und Komponenten aus dem Prototyp übernehmen
- Design-System:
  - `--accent: #00d4aa` (Cyan-Grün)
  - `--bg: #0a0c0f` (Fast Schwarz)
  - `--surface: #111418`
  - Fonts: Rajdhani (Headlines), Space Mono (Labels/Code), Inter (Body)
  - Stil: Dark industrial, minimalistisch

## Ziel-Infrastruktur
- Läuft als **Docker Compose Stack auf Unraid**
- Ollama läuft auf einem **separaten Rechner** im Heimnetz (nicht im selben Stack)
- Keine Cloud-Abhängigkeiten – alles lokal

## Stack
- **Backend:** Python 3.12 + FastAPI
- **Datenbank:** SQLite (via SQLModel/SQLAlchemy)
- **3D-Rendering:** trimesh + pyrender oder moderngl für STL→PNG Vorschaubilder
- **KI-Kategorisierung:** Qwen2.5-VL via Ollama REST API
- **Filewatcher:** watchdog (erkennt neue Dateien automatisch)
- **Frontend:** Vanilla HTML/CSS/JS (aus Prototyp), served by FastAPI

## Ollama-Konfiguration
```
OLLAMA_BASE_URL=http://<OLLAMA_IP>:11434
OLLAMA_MODEL=qwen2.5vl:7b
```
- Qwen2.5-VL bekommt: gerendertes Vorschaubild (PNG) + Dateipfad + Dateiname
- Gibt zurück: category, tags[], supports_needed, difficulty, print_notes

## Datenmodell (SQLite)

```python
class PrintFile(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str                        # Dateiname ohne Extension
    path: str                        # Absoluter Pfad im Container
    format: str                      # STL | 3MF | OBJ | LYS
    size_bytes: int
    category: str                    # miniatures|tools|deco|tech|cosplay|misc
    tags: str                        # JSON-Array als String
    supports_needed: bool = False
    difficulty: str = "medium"       # easy|medium|hard
    notes: str = ""
    favorite: bool = False
    print_status: str = "unprinted"  # unprinted|printing|printed
    thumbnail_path: str | None = None
    ai_processed: bool = False       # wurde bereits von KI analysiert?
    date_added: datetime = Field(default_factory=datetime.utcnow)
    date_modified: datetime = Field(default_factory=datetime.utcnow)
```

## Kategorien
| Key | Label | Icon |
|---|---|---|
| miniatures | Miniaturen | ⚔ |
| tools | Werkzeug | 🔧 |
| deco | Deko | ◎ |
| tech | Technik | ⊞ |
| cosplay | Cosplay | ⬟ |
| misc | Sonstiges | 📄 |

## API-Endpunkte (FastAPI)

```
GET  /api/files          – Liste aller Dateien (mit Filter/Suche/Sort Query-Params)
GET  /api/files/{id}     – Einzelne Datei Details
PUT  /api/files/{id}     – Datei aktualisieren (Kategorie, Tags, Status, Notizen, Favorit)
GET  /api/files/{id}/download  – Datei herunterladen
GET  /api/thumbnails/{id}      – Vorschaubild als PNG
POST /api/scan           – Manueller Scan des Verzeichnisses triggern
GET  /api/stats          – Statistiken (Anzahl, Größe, Kategorien)
GET  /api/settings       – Einstellungen lesen
PUT  /api/settings       – Einstellungen speichern
```

### Filter-Parameter für GET /api/files
```
?search=space+marine     – Freitextsuche (name, tags)
?category=miniatures     – Kategorie-Filter
?format=STL              – Format-Filter
?favorite=true           – Nur Favoriten
?status=printed          – Druckstatus-Filter
?sort=date|name|size     – Sortierung
?order=asc|desc
?limit=50&offset=0       – Pagination
```

## Projektstruktur
```
printvault/
├── docker-compose.yml
├── .env.example
├── CLAUDE.md
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py              – FastAPI App, Startup, Router-Registration
│   ├── database.py          – SQLite Setup, SQLModel Engine
│   ├── models.py            – PrintFile, Settings SQLModel-Klassen
│   ├── routers/
│   │   ├── files.py         – /api/files Endpunkte
│   │   ├── scan.py          – /api/scan + Scan-Logik
│   │   └── settings.py      – /api/settings
│   ├── services/
│   │   ├── scanner.py       – Verzeichnis-Scan, neue Dateien erkennen
│   │   ├── thumbnail.py     – STL/3MF → PNG Rendering (trimesh)
│   │   ├── ai_tagger.py     – Ollama API, Qwen2.5-VL Prompt + Parsing
│   │   └── watcher.py       – watchdog Filewatcher
│   └── static/              – Frontend-Dateien (HTML/CSS/JS)
│       └── index.html       – Aus Prototyp übernommen, API-connected
├── data/
│   ├── db/                  – SQLite Datenbankdatei (Volume)
│   └── thumbnails/          – Generierte Vorschaubilder (Volume)
└── ui/
    └── 3d-print-manager.html  – UI-Prototyp (Referenz)
```

## Docker Compose
```yaml
services:
  printvault:
    build: ./backend
    ports:
      - "8765:8000"
    volumes:
      - /mnt/user/3dprint:/files:ro      # Unraid Share, read-only
      - ./data/db:/app/data/db
      - ./data/thumbnails:/app/data/thumbnails
    environment:
      - FILES_DIR=/files
      - OLLAMA_BASE_URL=${OLLAMA_BASE_URL}
      - OLLAMA_MODEL=${OLLAMA_MODEL}
      - THUMBNAIL_DIR=/app/data/thumbnails
      - DB_PATH=/app/data/db/printvault.db
    restart: unless-stopped
```

## KI-Prompt für Qwen2.5-VL
```
Du bist ein Assistent für 3D-Druck-Dateiverwaltung.
Analysiere dieses Vorschaubild einer 3D-Druckdatei und den Dateipfad.

Dateipfad: {file_path}

Antworte NUR mit einem JSON-Objekt (kein Markdown, kein Text darum):
{
  "category": "miniatures|tools|deco|tech|cosplay|misc",
  "tags": ["tag1", "tag2", "tag3"],
  "supports_needed": true|false,
  "difficulty": "easy|medium|hard",
  "notes": "Kurze Beschreibung auf Deutsch, max 100 Zeichen"
}
```

## Wichtige Implementierungshinweise
- Thumbnail-Rendering läuft in einem separaten Thread (nicht blockierend)
- KI-Analyse läuft als Background-Task nach dem Thumbnail-Rendering
- `ai_processed=False` Dateien werden priorisiert in der Scan-Queue
- Bei Ollama-Fehler: Datei bleibt mit `category=misc`, `ai_processed=False` → retry beim nächsten Scan
- Dateien nur READ – niemals löschen oder verschieben (Volume ist :ro gemountet)
- SQLite WAL-Modus aktivieren für bessere Concurrent-Performance

## GitHub & CI/CD

### Repository-Struktur
```
github.com/DEIN-USERNAME/printvault
```

### GitHub Actions – automatischer Docker Build
Datei: `.github/workflows/docker.yml`
- Trigger: push auf `main`
- Baut das Docker-Image
- Pushed auf `ghcr.io/DEIN-USERNAME/printvault:latest`
- Auch einen Tag mit der Commit-SHA (für Rollbacks)

```yaml
# Wichtige Punkte für den Workflow:
# - uses: docker/build-push-action
# - registry: ghcr.io
# - username: ${{ github.actor }}
# - password: ${{ secrets.GITHUB_TOKEN }}  ← kein manuelles Secret nötig
# - tags: ghcr.io/DEIN-USERNAME/printvault:latest
```

### .gitignore
```
.env
data/
*.db
__pycache__/
*.pyc
.venv/
```

### Unraid – Image aktualisieren
Entweder manuell im Unraid Docker-Tab auf "Update" klicken,
oder Watchtower als Container für automatische Updates.

## Noch nicht implementiert (spätere Features)
- Multi-File-Sets erkennen (wenn mehrere STL zu einem Modell gehören)
- ZIP-Entpackung beim Import
- Druckzeit-Schätzung
- Slicer-Integration
