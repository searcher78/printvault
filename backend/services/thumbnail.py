import io
import logging
import os
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

THUMBNAIL_DIR = os.getenv("THUMBNAIL_DIR", "/app/data/thumbnails")
THUMBNAIL_SIZE = (512, 512)

# Design-system colours
_BG_COLOR   = "#0d0f12"
_BASE_COLOR = np.array([0.0, 0.831, 0.667])   # #00d4aa


def generate_thumbnail(file_path: str, file_id: int) -> Optional[str]:
    """Render a 3D file to a PNG thumbnail. Returns path or None on failure."""
    try:
        import trimesh

        loaded = trimesh.load(file_path)

        # Flatten scene graphs to a single mesh
        if isinstance(loaded, trimesh.Scene):
            if loaded.is_empty:
                logger.warning(f"Empty scene: {file_path}")
                return None
            meshes = [g for g in loaded.geometry.values()
                      if isinstance(g, trimesh.Trimesh) and not g.is_empty]
            if not meshes:
                return None
            mesh = trimesh.util.concatenate(meshes)
        elif isinstance(loaded, trimesh.Trimesh):
            mesh = loaded
        else:
            logger.warning(f"Unsupported mesh type {type(loaded)}: {file_path}")
            return None

        if mesh is None or mesh.is_empty:
            logger.warning(f"Empty mesh: {file_path}")
            return None

        # Normalise to unit sphere centred at origin
        mesh.apply_translation(-mesh.centroid)
        if mesh.scale > 0:
            mesh.apply_scale(1.0 / mesh.scale)

        os.makedirs(THUMBNAIL_DIR, exist_ok=True)
        out_path = os.path.join(THUMBNAIL_DIR, f"{file_id}.png")

        img = _render(mesh)
        img.save(out_path)
        logger.info(f"Thumbnail saved: {out_path}")
        return out_path

    except Exception as exc:
        logger.error(f"Thumbnail generation failed for {file_path}: {exc}")
        return None


def _render(mesh) -> "PIL.Image.Image":
    """
    Matplotlib Agg renderer with per-face Lambert + ambient shading.
    No OpenGL or display required.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    from PIL import Image

    verts  = mesh.vertices
    faces  = mesh.faces
    normals = mesh.face_normals   # (F, 3) – trimesh keeps these normalised

    # Downsample very large meshes for performance
    max_faces = 10_000
    if len(faces) > max_faces:
        idx     = np.random.choice(len(faces), max_faces, replace=False)
        faces   = faces[idx]
        normals = normals[idx]

    polys = verts[faces]   # (N, 3, 3)

    # ── Lighting ─────────────────────────────────────────────────────────────
    # Two lights: key (upper-right-front) + fill (left)
    key_dir  = np.array([ 0.6,  0.4,  1.0]); key_dir  /= np.linalg.norm(key_dir)
    fill_dir = np.array([-1.0,  0.2,  0.3]); fill_dir /= np.linalg.norm(fill_dir)

    key_intensity  = 0.65
    fill_intensity = 0.20
    ambient        = 0.20

    diffuse_key  = np.clip(normals @ key_dir,  0, 1)
    diffuse_fill = np.clip(normals @ fill_dir, 0, 1)

    shading = ambient + key_intensity * diffuse_key + fill_intensity * diffuse_fill
    shading = np.clip(shading, 0, 1)[:, np.newaxis]   # (N, 1)

    # Per-face RGBA colours
    face_colors = np.hstack([
        _BASE_COLOR * shading,                  # RGB shaded
        np.full((len(faces), 1), 0.95),         # alpha
    ])

    # ── Render ────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(5.12, 5.12), dpi=100, facecolor=_BG_COLOR)
    ax  = fig.add_axes([0, 0, 1, 1], projection="3d", facecolor=_BG_COLOR)

    col = Poly3DCollection(polys, linewidths=0, edgecolors="none", shade=False)
    col.set_facecolors(face_colors)
    ax.add_collection3d(col)

    lim = 1.05
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_zlim(-lim, lim)
    ax.set_axis_off()
    ax.view_init(elev=28, azim=45)

    for pane in (ax.xaxis.pane, ax.yaxis.pane, ax.zaxis.pane):
        pane.fill = False
        pane.set_edgecolor("none")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight",
                pad_inches=0, facecolor=_BG_COLOR)
    plt.close(fig)
    buf.seek(0)

    from PIL import Image
    return Image.open(buf).convert("RGB").resize(THUMBNAIL_SIZE, Image.LANCZOS)
