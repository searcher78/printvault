import logging
import tarfile
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_3D = {".stl": "STL", ".3mf": "3MF", ".obj": "OBJ", ".lys": "LYS"}

ARCHIVE_SUFFIXES = {".zip", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".tbz", ".7z", ".rar"}


def is_archive(filename: str) -> bool:
    name = filename.lower()
    return (
        any(name.endswith(s) for s in ARCHIVE_SUFFIXES)
        or name.endswith(".tar.gz")
        or name.endswith(".tar.bz2")
        or name.endswith(".tar.xz")
    )


def extract_archive(archive_path: Path, dest_dir: Path) -> list[Path]:
    """Extract archive to dest_dir. Returns list of 3D print files found."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = archive_path.name.lower()

    if name.endswith(".zip"):
        _extract_zip(archive_path, dest_dir)
    elif (
        name.endswith(".tar.gz") or name.endswith(".tgz")
        or name.endswith(".tar.bz2") or name.endswith(".tbz")
        or name.endswith(".tar.xz") or name.endswith(".tar")
    ):
        _extract_tar(archive_path, dest_dir)
    elif name.endswith(".7z"):
        _extract_7z(archive_path, dest_dir)
    elif name.endswith(".rar"):
        _extract_rar(archive_path, dest_dir)
    else:
        raise ValueError(f"Unbekanntes Archivformat: {archive_path.name}")

    return _collect_3d_files(dest_dir)


def _safe_target(dest: Path, member_path: str) -> Path | None:
    """ZIP-Slip-Schutz: None wenn der Pfad außerhalb von dest landet."""
    try:
        target = (dest / member_path).resolve()
        target.relative_to(dest.resolve())
        return target
    except ValueError:
        logger.warning("ZIP-Slip blockiert: %s", member_path)
        return None


def _collect_3d_files(directory: Path) -> list[Path]:
    return [p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_3D.keys()]


def _extract_zip(archive_path: Path, dest_dir: Path) -> None:
    with zipfile.ZipFile(archive_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            target = _safe_target(dest_dir, info.filename)
            if target is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())


def _extract_tar(archive_path: Path, dest_dir: Path) -> None:
    with tarfile.open(archive_path, "r:*") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            target = _safe_target(dest_dir, member.name)
            if target is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            f = tf.extractfile(member)
            if f:
                with open(target, "wb") as dst:
                    dst.write(f.read())


def _extract_7z(archive_path: Path, dest_dir: Path) -> None:
    import py7zr
    with py7zr.SevenZipFile(archive_path, mode="r") as zf:
        zf.extractall(path=dest_dir)


def _extract_rar(archive_path: Path, dest_dir: Path) -> None:
    import subprocess
    result = subprocess.run(
        ["unrar-free", "-x", "-f", str(archive_path), str(dest_dir) + "/"],
        capture_output=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"unrar-free failed (exit {result.returncode}): "
            f"{result.stderr.decode(errors='replace')[:500]}"
        )
