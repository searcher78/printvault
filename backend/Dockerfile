FROM python:3.12-slim

# System deps for pyrender (OSMesa headless OpenGL) + trimesh
RUN apt-get update && apt-get install -y \
    libgles2-mesa-dev \
    libosmesa6-dev \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data/db /app/data/thumbnails

ENV PYTHONUNBUFFERED=1
ENV PYOPENGL_PLATFORM=osmesa

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
