import io
import logging
import os
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

THUMBNAIL_DIR = os.getenv("THUMBNAIL_DIR", "/app/data/thumbnails")
THUMBNAIL_SIZE = (512, 512)

# Accent colour from design system
_MESH_COLOR = "#00d4aa"
_BG_COLOR   = "#0d0f12"


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
            mesh = trimesh.util.concatenate(
                [g for g in loaded.geometry.values() if isinstance(g, trimesh.Trimesh)]
            )
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

        img = _render_matplotlib(mesh)
        img.save(out_path)
        logger.info(f"Thumbnail saved: {out_path}")
        return out_path

    except Exception as exc:
        logger.error(f"Thumbnail generation failed for {file_path}: {exc}")
        return None


def _render_matplotlib(mesh) -> "PIL.Image.Image":
    """Software-render mesh with matplotlib Agg backend (no display/OpenGL needed)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    from PIL import Image

    verts = mesh.vertices
    faces = mesh.faces

    # Limit face count for performance – downsample large meshes
    max_faces = 8000
    if len(faces) > max_faces:
        idx = np.random.choice(len(faces), max_faces, replace=False)
        faces = faces[idx]

    polys = verts[faces]  # shape (N, 3, 3)

    fig = plt.figure(figsize=(5.12, 5.12), dpi=100, facecolor=_BG_COLOR)
    ax = fig.add_axes([0, 0, 1, 1], projection="3d", facecolor=_BG_COLOR)

    col = Poly3DCollection(
        polys,
        alpha=0.92,
        linewidths=0,
        edgecolors="none",
    )
    col.set_facecolor(_MESH_COLOR)
    ax.add_collection3d(col)

    # Fit axes to mesh bounds
    lim = 1.05
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_zlim(-lim, lim)
    ax.set_axis_off()

    # Isometric-ish view
    ax.view_init(elev=28, azim=45)

    # Remove grey panes
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
