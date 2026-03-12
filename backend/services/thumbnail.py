import io
import logging
import os
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

THUMBNAIL_DIR = os.getenv("THUMBNAIL_DIR", "/app/data/thumbnails")
THUMBNAIL_SIZE = (512, 512)

# Design-system colour (#00d4aa)
_BASE_COLOR = np.array([0.0, 0.831, 0.667], dtype=np.float32)

# Background gradient (dark top → darker bottom)
_BG_TOP = np.array([0.050, 0.057, 0.068], dtype=np.float32)
_BG_BOT = np.array([0.033, 0.038, 0.047], dtype=np.float32)


def generate_thumbnail(file_path: str, file_id: int) -> Optional[str]:
    """Render a 3D file to a PNG thumbnail. Returns path or None on failure."""
    try:
        import trimesh

        loaded = trimesh.load(file_path)

        if isinstance(loaded, trimesh.Scene):
            if loaded.is_empty:
                logger.warning("Empty scene: %s", file_path)
                return None
            meshes = [g for g in loaded.geometry.values()
                      if isinstance(g, trimesh.Trimesh) and not g.is_empty]
            if not meshes:
                return None
            mesh = trimesh.util.concatenate(meshes)
        elif isinstance(loaded, trimesh.Trimesh):
            mesh = loaded
        else:
            logger.warning("Unsupported mesh type %s: %s", type(loaded), file_path)
            return None

        if mesh is None or mesh.is_empty:
            logger.warning("Empty mesh: %s", file_path)
            return None

        # Normalise: centre at origin, scale to unit diagonal
        mesh.apply_translation(-mesh.centroid)
        if mesh.scale > 0:
            mesh.apply_scale(1.0 / mesh.scale)

        os.makedirs(THUMBNAIL_DIR, exist_ok=True)
        out_path = os.path.join(THUMBNAIL_DIR, f"{file_id}.png")

        try:
            img = _render_rasterize(mesh)
        except Exception as e:
            logger.warning("Rasterizer failed (%s), falling back to matplotlib", e)
            img = _render_matplotlib(mesh)

        img.save(out_path)
        logger.info("Thumbnail saved: %s", out_path)
        return out_path

    except Exception as exc:
        logger.error("Thumbnail generation failed for %s: %s", file_path, exc)
        return None


# ── Z-Buffer Rasterizer ───────────────────────────────────────────────────────

def _render_rasterize(mesh) -> "PIL.Image.Image":
    """
    Software Z-buffer rasterizer:
    - Orthographic projection (same camera as before)
    - Smooth Phong shading (barycentric vertex-normal interpolation)
    - 3-point lighting: key + fill + rim + Blinn-Phong specular
    - Fresnel-like silhouette darkening
    - O(W*H) memory – no BVH, no ray arrays
    """
    from PIL import Image

    W, H = THUMBNAIL_SIZE

    # ── Camera ────────────────────────────────────────────────────────────────
    cam_dir = np.array([1.0, 0.75, 0.55], dtype=np.float32)
    cam_dir /= np.linalg.norm(cam_dir)
    forward = -cam_dir

    world_up = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    right = np.cross(forward, world_up).astype(np.float32)
    right /= np.linalg.norm(right)
    up = np.cross(right, forward).astype(np.float32)

    cam_pos = cam_dir * 5.0

    # ── Project all vertices to screen space ──────────────────────────────────
    verts = mesh.vertices.astype(np.float32)
    rel = verts - cam_pos         # (V, 3) – relative to camera
    scale = 0.58

    sx =  (rel @ right) / scale   # (V,) in [-1, 1]
    sy = -(rel @ up)    / scale   # (V,) in [-1, 1], flipped for image coords
    sz =   rel @ (-forward)       # (V,) depth – larger = farther

    px = (sx + 1.0) * 0.5 * W    # pixel x
    py = (sy + 1.0) * 0.5 * H    # pixel y

    # ── Buffers ───────────────────────────────────────────────────────────────
    z_buf     = np.full((H, W), np.inf, dtype=np.float32)
    normal_buf = np.zeros((H, W, 3), dtype=np.float32)
    hit_buf   = np.zeros((H, W), dtype=bool)

    # Background gradient
    y_frac = np.linspace(0, 1, H, dtype=np.float32)
    bg_rows = _BG_TOP[np.newaxis, :] * (1.0 - y_frac[:, np.newaxis]) + \
              _BG_BOT[np.newaxis, :] * y_frac[:, np.newaxis]          # (H, 3)
    color_buf = np.broadcast_to(bg_rows[:, np.newaxis, :], (H, W, 3)).copy()

    # ── Per-face screen coords ────────────────────────────────────────────────
    faces = mesh.faces             # (F, 3)
    vn    = mesh.vertex_normals.astype(np.float32)  # (V, 3)

    i0, i1, i2 = faces[:, 0], faces[:, 1], faces[:, 2]
    x0, y0_, z0 = px[i0], py[i0], sz[i0]
    x1, y1_, z1 = px[i1], py[i1], sz[i1]
    x2, y2_, z2 = px[i2], py[i2], sz[i2]

    # Edge vectors for barycentric computation
    dx10 = x1 - x0;  dy10 = y1_ - y0_
    dx20 = x2 - x0;  dy20 = y2_ - y0_

    # Signed area (positive = front-facing in our coord system)
    area2 = dx10 * dy20 - dy10 * dx20  # (F,)

    # ── Rasterize each face ───────────────────────────────────────────────────
    for fi in range(len(faces)):
        a2 = area2[fi]
        if abs(a2) < 1e-6:
            continue

        xmin = max(0,     int(min(x0[fi], x1[fi], x2[fi])))
        xmax = min(W - 1, int(max(x0[fi], x1[fi], x2[fi])) + 1)
        ymin = max(0,     int(min(y0_[fi], y1_[fi], y2_[fi])))
        ymax = min(H - 1, int(max(y0_[fi], y1_[fi], y2_[fi])) + 1)

        if xmax < xmin or ymax < ymin:
            continue

        # Pixel-centre coordinates for this bounding box
        xs = np.arange(xmin, xmax + 1, dtype=np.float32) + 0.5
        ys = np.arange(ymin, ymax + 1, dtype=np.float32) + 0.5
        gx, gy = np.meshgrid(xs, ys)  # (rows, cols)

        dxp0 = gx - x0[fi]
        dyp0 = gy - y0_[fi]

        # Barycentric coords (w0+w1+w2 = 1)
        inv_a2 = 1.0 / a2
        w1 = (dxp0 * dy20[fi] - dyp0 * dx20[fi]) * inv_a2
        w2 = (dx10[fi] * dyp0 - dy10[fi] * dxp0) * inv_a2
        w0 = 1.0 - w1 - w2

        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue

        # Depth interpolation
        z = w0 * z0[fi] + w1 * z1[fi] + w2 * z2[fi]

        # Absolute pixel indices
        pys_idx = np.arange(ymin, ymax + 1)
        pxs_idx = np.arange(xmin, xmax + 1)
        PY, PX = np.meshgrid(pys_idx, pxs_idx, indexing='ij')

        mask = inside & (z < z_buf[PY, PX])
        if not mask.any():
            continue

        z_buf[PY[mask], PX[mask]] = z[mask]
        hit_buf[PY[mask], PX[mask]] = True

        # Smooth normals via barycentric interpolation
        n_interp = (
            w0[mask, np.newaxis] * vn[i0[fi]]
            + w1[mask, np.newaxis] * vn[i1[fi]]
            + w2[mask, np.newaxis] * vn[i2[fi]]
        )
        normal_buf[PY[mask], PX[mask]] = n_interp

    # ── Shading for hit pixels ────────────────────────────────────────────────
    if hit_buf.any():
        norms = normal_buf[hit_buf]      # (N, 3)
        nlen  = np.linalg.norm(norms, axis=1, keepdims=True)
        norms = np.where(nlen > 1e-8, norms / np.maximum(nlen, 1e-8),
                         np.zeros_like(norms))

        view  = (-forward).astype(np.float32)
        l_key = np.array([ 0.60,  0.40,  1.00], np.float32); l_key /= np.linalg.norm(l_key)
        l_fil = np.array([-1.00,  0.30,  0.45], np.float32); l_fil /= np.linalg.norm(l_fil)
        l_rim = np.array([-0.35, -0.80,  0.30], np.float32); l_rim /= np.linalg.norm(l_rim)
        h_key = l_key + view; h_key /= np.linalg.norm(h_key)

        d_key = np.clip(norms @ l_key, 0, 1)
        d_fil = np.clip(norms @ l_fil, 0, 1)
        d_rim = np.clip(norms @ l_rim, 0, 1)
        spec  = np.clip(norms @ h_key, 0, 1).astype(np.float32) ** 42

        shading = (
            0.18                 # ambient
            + 0.82 * d_key       # key light
            + 0.22 * d_fil       # fill light
            + 0.10 * d_rim       # rim light
            + 0.45 * spec        # specular highlight
        )

        color = (
            _BASE_COLOR[np.newaxis, :] * shading[:, np.newaxis]
            + np.array([0.85, 0.95, 0.90], np.float32) * (0.28 * spec[:, np.newaxis])
        )
        color_buf[hit_buf] = np.clip(color, 0, 1)

    img_arr = np.clip(color_buf * 255, 0, 255).astype(np.uint8)
    return Image.fromarray(img_arr)


# ── Matplotlib fallback ───────────────────────────────────────────────────────

def _render_matplotlib(mesh) -> "PIL.Image.Image":
    """Lambert-shaded matplotlib fallback (used if rasterizer fails)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    from PIL import Image

    verts   = mesh.vertices
    faces   = mesh.faces
    normals = mesh.face_normals

    max_faces = 10_000
    if len(faces) > max_faces:
        idx     = np.random.choice(len(faces), max_faces, replace=False)
        faces   = faces[idx]
        normals = normals[idx]

    polys = verts[faces]

    key_dir  = np.array([ 0.6,  0.4,  1.0]); key_dir  /= np.linalg.norm(key_dir)
    fill_dir = np.array([-1.0,  0.2,  0.3]); fill_dir /= np.linalg.norm(fill_dir)

    shading = np.clip(
        0.20 + 0.65 * np.clip(normals @ key_dir, 0, 1)
             + 0.20 * np.clip(normals @ fill_dir, 0, 1),
        0, 1
    )[:, np.newaxis]

    face_colors = np.hstack([_BASE_COLOR * shading, np.full((len(faces), 1), 0.95)])

    fig = plt.figure(figsize=(5.12, 5.12), dpi=100, facecolor="#0d0f12")
    ax  = fig.add_axes([0, 0, 1, 1], projection="3d", facecolor="#0d0f12")

    col = Poly3DCollection(polys, linewidths=0, edgecolors="none", shade=False)
    col.set_facecolors(face_colors)
    ax.add_collection3d(col)

    lim = 1.05
    ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim); ax.set_zlim(-lim, lim)
    ax.set_axis_off()
    ax.view_init(elev=28, azim=45)
    for pane in (ax.xaxis.pane, ax.yaxis.pane, ax.zaxis.pane):
        pane.fill = False; pane.set_edgecolor("none")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight",
                pad_inches=0, facecolor="#0d0f12")
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGB").resize(THUMBNAIL_SIZE, Image.LANCZOS)
