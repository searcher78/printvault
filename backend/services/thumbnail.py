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

        # Simplify very large meshes so BVH construction stays fast
        if len(mesh.faces) > 150_000:
            try:
                mesh = mesh.simplify_quadric_decimation(150_000)
            except Exception:
                pass  # keep original if simplification fails

        os.makedirs(THUMBNAIL_DIR, exist_ok=True)
        out_path = os.path.join(THUMBNAIL_DIR, f"{file_id}.png")

        try:
            img = _render_raycast(mesh)
        except Exception as e:
            logger.warning("Raycast renderer failed (%s), falling back to matplotlib", e)
            img = _render_matplotlib(mesh)

        img.save(out_path)
        logger.info("Thumbnail saved: %s", out_path)
        return out_path

    except Exception as exc:
        logger.error("Thumbnail generation failed for %s: %s", file_path, exc)
        return None


# ── Ray-cast renderer ─────────────────────────────────────────────────────────

def _render_raycast(mesh) -> "PIL.Image.Image":
    """
    Software ray-caster with:
    - Orthographic projection (consistent framing)
    - Smooth Phong shading (barycentric vertex-normal interpolation)
    - 3-point lighting: key + fill + rim
    - Blinn-Phong specular highlights
    - Fresnel-like silhouette darkening
    - 2× supersampling → LANCZOS downsample for anti-aliasing
    """
    import trimesh
    from PIL import Image

    out_w, out_h = THUMBNAIL_SIZE
    W, H = out_w, out_h

    # ── Camera ────────────────────────────────────────────────────────────────
    cam_dir = np.array([1.0, 0.75, 0.55], dtype=np.float32)
    cam_dir /= np.linalg.norm(cam_dir)
    forward = -cam_dir

    world_up = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    right = np.cross(forward, world_up).astype(np.float32)
    right /= np.linalg.norm(right)
    up = np.cross(right, forward).astype(np.float32)

    # ── Ray grid (orthographic) ───────────────────────────────────────────────
    # mesh diagonal = 1 after normalisation; scale 0.72 → fills ~72% of frame
    scale = 0.72
    xs = np.linspace(-scale, scale, W, dtype=np.float32)
    ys = np.linspace( scale, -scale, H, dtype=np.float32)
    xx, yy = np.meshgrid(xs, ys)  # (H, W)

    cam_pos = cam_dir * 5.0
    # origins: camera plane translated by (right * x) + (up * y)
    origins = (
        cam_pos
        + xx[..., np.newaxis] * right
        + yy[..., np.newaxis] * up
    ).reshape(-1, 3).astype(np.float64)  # trimesh expects float64
    directions = np.broadcast_to(forward.astype(np.float64).reshape(1, 3), (W * H, 3)).copy()

    # ── Intersection ─────────────────────────────────────────────────────────
    intersector = trimesh.ray.ray_triangle.RayMeshIntersector(mesh)
    locations, index_ray, index_tri = intersector.intersects_location(
        origins, directions, multiple_hits=False
    )

    # ── Background ────────────────────────────────────────────────────────────
    y_idx  = np.arange(H * W, dtype=np.float32) // W
    y_frac = (y_idx / max(H - 1, 1)).reshape(-1, 1)
    pixels = (_BG_TOP * (1.0 - y_frac) + _BG_BOT * y_frac).astype(np.float32)

    # ── Shading ───────────────────────────────────────────────────────────────
    if len(index_ray) > 0:
        # Smooth normals: barycentric interpolation of vertex normals
        triangles = mesh.triangles[index_tri]  # (N, 3, 3)
        bary = trimesh.triangles.points_to_barycentric(triangles, locations)

        face_verts = mesh.faces[index_tri]      # (N, 3)
        vn = mesh.vertex_normals.astype(np.float32)  # (V, 3)
        smooth_n = (
            bary[:, 0:1] * vn[face_verts[:, 0]] +
            bary[:, 1:2] * vn[face_verts[:, 1]] +
            bary[:, 2:3] * vn[face_verts[:, 2]]
        )
        nlen = np.linalg.norm(smooth_n, axis=1, keepdims=True)
        smooth_n = np.where(nlen > 1e-8, smooth_n / nlen,
                            mesh.face_normals[index_tri].astype(np.float32))

        view = (-forward).astype(np.float32)

        # 3-point lights
        l_key = np.array([ 0.60,  0.40,  1.00], np.float32); l_key  /= np.linalg.norm(l_key)
        l_fil = np.array([-1.00,  0.30,  0.45], np.float32); l_fil  /= np.linalg.norm(l_fil)
        l_rim = np.array([-0.35, -0.80,  0.30], np.float32); l_rim  /= np.linalg.norm(l_rim)

        d_key = np.clip(smooth_n @ l_key, 0, 1)
        d_fil = np.clip(smooth_n @ l_fil, 0, 1)
        d_rim = np.clip(smooth_n @ l_rim, 0, 1)

        # Blinn-Phong specular (key light)
        h_key = l_key + view; h_key /= np.linalg.norm(h_key)
        spec = np.clip(smooth_n @ h_key, 0, 1).astype(np.float32) ** 42

        # Fresnel-like silhouette darkening: faces at grazing angle get darker
        ndotv = np.clip(smooth_n @ view, 0, 1)
        fresnel = ndotv ** 1.5  # smooth falloff at silhouette

        shading = (
            0.12                  # ambient
            + 0.68 * d_key        # key light
            + 0.16 * d_fil        # fill light
            + 0.10 * d_rim        # rim  light
        ) * fresnel + 0.38 * spec

        color = (
            _BASE_COLOR[np.newaxis, :] * shading[:, np.newaxis]
            + np.array([0.85, 0.95, 0.90], np.float32) * (0.25 * spec[:, np.newaxis])
        )
        pixels[index_ray] = np.clip(color, 0, 1)

    img_arr = np.clip(pixels.reshape(H, W, 3) * 255, 0, 255).astype(np.uint8)
    return Image.fromarray(img_arr)


# ── Matplotlib fallback ───────────────────────────────────────────────────────

def _render_matplotlib(mesh) -> "PIL.Image.Image":
    """Lambert-shaded matplotlib fallback (used if ray-caster fails)."""
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
