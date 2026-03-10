FROM python:3.12-slim

# System deps for pyrender (OSMesa headless OpenGL) + trimesh
# Works on both Debian Bookworm and Trixie (python:3.12-slim base)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libosmesa6 \
    libgomp1 \
    && ( apt-get install -y --no-install-recommends libgl1-mesa-glx libglib2.0-0 \
         || apt-get install -y --no-install-recommends libgl1 libglib2.0-0t64 ) \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data/db /app/data/thumbnails

ENV PYTHONUNBUFFERED=1
ENV PYOPENGL_PLATFORM=osmesa

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
