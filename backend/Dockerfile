FROM python:3.12-slim

# System deps: libgomp (trimesh/numpy), libglib2 (matplotlib)
# libglib2.0-0 was renamed to libglib2.0-0t64 in Debian Trixie
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && ( apt-get install -y --no-install-recommends libglib2.0-0 2>/dev/null \
         || apt-get install -y --no-install-recommends libglib2.0-0t64 ) \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data/db /app/data/thumbnails

ENV PYTHONUNBUFFERED=1
ENV PYOPENGL_PLATFORM=osmesa

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
