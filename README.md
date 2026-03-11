# PrintVault

A self-hosted 3D print file manager for Unraid (and any Docker host). Scans a local directory for STL, 3MF, and OBJ files, generates preview thumbnails, and automatically categorizes files using AI via Ollama. Browse, search, filter, and download your print files through a clean web interface.

![PrintVault Screenshot](ui/preview.png)

## Features

- **Auto-scan** – detects new files automatically via filesystem watcher
- **Thumbnail generation** – renders STL/3MF/OBJ files to PNG previews (no GPU required)
- **AI categorization** – uses Qwen2.5-VL via Ollama to tag and categorize files
- **Interactive 3D viewer** – rotate, zoom, and pan models directly in the browser (Three.js, no CDN)
- **Folder tree** – collapsible folder hierarchy in the sidebar; clicking a folder shows all files including subfolders
- **Folder preview images** – if a folder contains an image file (e.g. a photo of the finished print), it is shown as a thumbnail in the sidebar and as a hero banner when browsing the folder
- **Rename files & folders** – rename files and folders directly from the UI; changes are applied on disk
- **Search & filter** – by name, tag, category, format, print status, and favorite
- **Edit metadata** – categories, tags, difficulty, support requirements, notes, print status
- **Dynamic categories** – create and delete custom categories from the sidebar
- **Download** – one-click download of the original file

## Stack

- **Backend:** Python 3.12 + FastAPI
- **Database:** SQLite (via SQLModel)
- **Thumbnail rendering:** trimesh + matplotlib (headless, no display needed)
- **AI tagging:** Qwen2.5-VL via Ollama REST API
- **Frontend:** Vanilla HTML/CSS/JS + Three.js r0.160.0 (served locally)

---

## Setup on Unraid

### Prerequisites

- Unraid with the **Community Applications** plugin
- **Docker** enabled on Unraid
- An **Ollama** instance running somewhere on your local network (can be another machine)
  - Model pulled: `ollama pull qwen2.5vl:7b`

---

### 1. Clone the repository

Open a terminal on your Unraid server (or SSH into it):

```bash
cd /mnt/user/appdata
git clone https://github.com/searcher78/printvault.git
cd printvault
```

---

### 2. Create the `.env` file

```bash
cp .env.example .env
nano .env
```

Set your Ollama address and model:

```env
OLLAMA_BASE_URL=http://192.168.1.x:11434
OLLAMA_MODEL=qwen2.5vl:7b
```

---

### 3. Edit `docker-compose.yml`

Open `docker-compose.yml` and update the volume path to point to your 3D print files share:

```yaml
volumes:
  - /mnt/user/3dprint:/files   # <-- change to your actual share path
  - ./data/db:/app/data/db
  - ./data/thumbnails:/app/data/thumbnails
```

The volume is mounted read-write to allow renaming files and folders from the UI.

---

### 4. Start the stack

```bash
docker compose up -d --build
```

PrintVault is now available at `http://<your-unraid-ip>:8765`.

---

### 5. Trigger the initial scan

Open the web UI and click **Scan** in the top bar, or call the API directly:

```bash
curl -X POST http://<your-unraid-ip>:8765/api/scan
```

The scanner will:
1. Find all STL, 3MF, and OBJ files in your share
2. Render a thumbnail for each file
3. Send thumbnails to Ollama for AI categorization

This may take a while depending on the number of files. Progress is visible in the Docker logs:

```bash
docker compose logs -f
```

---

## Updating

```bash
cd /mnt/user/appdata/printvault
git pull
docker compose up -d --build
```

Or use **Watchtower** to update automatically when a new image is published to `ghcr.io/searcher78/printvault:latest`.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `FILES_DIR` | `/files` | Path inside the container where files are mounted |
| `OLLAMA_BASE_URL` | – | Ollama API base URL, e.g. `http://192.168.1.x:11434` |
| `OLLAMA_MODEL` | – | Ollama model name, e.g. `qwen2.5vl:7b` |
| `THUMBNAIL_DIR` | `/app/data/thumbnails` | Where generated thumbnails are stored |
| `DB_PATH` | `/app/data/db/printvault.db` | SQLite database file path |

---

## API Overview

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/files` | List files (with filter/search/sort params) |
| `GET` | `/api/files/{id}` | File details |
| `PUT` | `/api/files/{id}` | Update metadata |
| `GET` | `/api/files/{id}/download` | Download original file |
| `GET` | `/api/thumbnails/{id}` | Thumbnail PNG |
| `GET` | `/api/folders` | Folder list with file counts and image flag |
| `GET` | `/api/folder-image` | Serve the preview image of a folder |
| `POST` | `/api/files/{id}/rename` | Rename a file on disk |
| `POST` | `/api/folders/rename` | Rename a folder on disk |
| `POST` | `/api/scan` | Trigger a manual scan |
| `POST` | `/api/reprocess` | Re-render all thumbnails |
| `GET` | `/api/stats` | Library statistics |
| `GET/PUT` | `/api/settings` | Read/write settings |

---

## License

MIT
