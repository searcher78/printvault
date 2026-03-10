import io
import logging
import os
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

THUMBNAIL_DIR = os.getenv("THUMBNAIL_DIR", "/app/data/thumbnails")
THUMBNAIL_SIZE = (512, 512)


def generate_thumbnail(file_path: str, file_id: int) -> Optional[str]:
    """Render a 3D file to a PNG thumbnail. Returns path or None on failure."""
    try:
        import trimesh

        mesh = trimesh.load(file_path, force="mesh")
        if mesh is None or (hasattr(mesh, "is_empty") and mesh.is_empty):
            logger.warning(f"Empty or invalid mesh: {file_path}")
            return None

        # Normalize to unit sphere centered at origin
        mesh.apply_translation(-mesh.centroid)
        if mesh.scale > 0:
            mesh.apply_scale(1.0 / mesh.scale)

        os.makedirs(THUMBNAIL_DIR, exist_ok=True)
        out_path = os.path.join(THUMBNAIL_DIR, f"{file_id}.png")

        img = None
        for renderer in (_render_pyrender, _render_trimesh_scene):
            try:
                img = renderer(mesh)
                break
            except Exception as exc:
                logger.warning(f"Renderer {renderer.__name__} failed for {file_path}: {exc}")

        if img is None:
            logger.error(f"All renderers failed for {file_path}")
            return None

        img.save(out_path)
        logger.info(f"Thumbnail saved: {out_path}")
        return out_path

    except Exception as exc:
        logger.error(f"Thumbnail generation failed for {file_path}: {exc}")
        return None


def _camera_pose() -> np.ndarray:
    """Isometric camera pose (elevated 30°, rotated 45° around Z)."""
    # Build view matrix: place camera at (1.5, 1.5, 1.5), look at origin
    eye = np.array([1.5, 1.5, 1.5])
    target = np.zeros(3)
    up = np.array([0.0, 0.0, 1.0])

    z = eye - target
    z /= np.linalg.norm(z)
    x = np.cross(up, z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)

    pose = np.eye(4)
    pose[:3, 0] = x
    pose[:3, 1] = y
    pose[:3, 2] = z
    pose[:3, 3] = eye
    return pose


def _render_pyrender(mesh) -> "PIL.Image.Image":
    import pyrender
    from PIL import Image

    pr_mesh = pyrender.Mesh.from_trimesh(mesh)
    scene = pyrender.Scene(
        ambient_light=[0.4, 0.4, 0.4],
        bg_color=[0.07, 0.07, 0.1, 1.0],
    )
    scene.add(pr_mesh)

    cam = pyrender.PerspectiveCamera(yfov=np.pi / 3.0, znear=0.01, zfar=100.0)
    pose = _camera_pose()
    scene.add(cam, pose=pose)

    light = pyrender.DirectionalLight(color=[1.0, 1.0, 1.0], intensity=4.0)
    scene.add(light, pose=pose)

    renderer = pyrender.OffscreenRenderer(*THUMBNAIL_SIZE)
    color, _ = renderer.render(scene)
    renderer.delete()
    return Image.fromarray(color)


def _render_trimesh_scene(mesh) -> "PIL.Image.Image":
    from PIL import Image

    scene = mesh.scene()
    png_bytes = scene.save_image(resolution=THUMBNAIL_SIZE, visible=False)
    return Image.open(io.BytesIO(png_bytes))
