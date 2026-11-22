import hashlib
import os
import re
import shutil
from pathlib import Path
from app.config import settings
from app.core.exceptions import ClipStudioException


class StorageException(ClipStudioException):
    """Storage or disk management exception."""
    pass


def sanitize_filename(filename: str) -> str:
    """Sanitize user-provided filename to prevent directory traversal and filesystem issues."""
    # Remove null bytes and directory separators
    cleaned = filename.replace("\x00", "").replace("/", "_").replace("\\", "_")
    # Separate stem and extension
    path_obj = Path(cleaned)
    stem = path_obj.stem
    ext = path_obj.suffix.lower()

    # Normalize stem: allow alphanumeric, dashes, underscores
    sanitized_stem = re.sub(r"[^a-zA-Z0-9_\-]", "_", stem)
    sanitized_stem = re.sub(r"_+", "_", sanitized_stem).strip("_")

    if not sanitized_stem:
        sanitized_stem = "imported_media"

    # Truncate stem if excessively long (Windows MAX_PATH defense)
    if len(sanitized_stem) > 100:
        sanitized_stem = sanitized_stem[:100]

    # Validate extension: alphanumeric only up to 10 chars
    sanitized_ext = re.sub(r"[^a-zA-Z0-9]", "", ext)
    if sanitized_ext:
        return f"{sanitized_stem}.{sanitized_ext}"
    return f"{sanitized_stem}.mp4"


def check_disk_space(
    required_bytes: int,
    reserve_bytes: int | None = None,
    storage_dir: Path | None = None,
) -> tuple[bool, int, str]:
    """Verify that available storage exceeds required bytes plus minimum reserve."""
    target_dir = storage_dir or settings.STORAGE_DIR
    reserve = reserve_bytes if reserve_bytes is not None else settings.MIN_FREE_DISK_RESERVE_BYTES

    try:
        usage = shutil.disk_usage(target_dir)
        free_bytes = usage.free
    except Exception as exc:
        return False, 0, f"Failed to check disk usage: {exc}"

    needed = required_bytes + reserve
    if free_bytes < needed:
        free_mb = free_bytes / (1024 * 1024)
        needed_mb = needed / (1024 * 1024)
        return False, free_bytes, (
            f"Insufficient disk space. Available: {free_mb:.1f} MB, "
            f"Required (with 1 GB safety reserve): {needed_mb:.1f} MB."
        )

    return True, free_bytes, "Disk space sufficient"


def compute_sha256_stream(file_path: Path, chunk_size: int = 65536) -> str:
    """Compute SHA-256 fingerprint incrementally in 64 KB slices without loading file into RAM."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def safe_resolve_path(relative_path: str, storage_root: Path | None = None) -> Path:
    """Safely resolve a relative path against storage root, preventing directory traversal."""
    root = (storage_root or settings.STORAGE_DIR).resolve()
    # Normalize path separators
    clean_rel = relative_path.replace("\\", "/").lstrip("/")
    target = (root / clean_rel).resolve()

    # Enforce confinement within root boundary
    try:
        target.relative_to(root)
    except ValueError:
        raise StorageException(f"Path traversal detected: {relative_path}")

    return target


def atomic_promote_file(source_temp_path: Path, target_path: Path) -> Path:
    """Atomically promote staged temporary file to permanent storage location."""
    if not source_temp_path.exists():
        raise StorageException(f"Source file does not exist: {source_temp_path}")

    # Ensure destination directory exists
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Perform atomic replace (same filesystem on Windows)
    os.replace(source_temp_path, target_path)
    return target_path


def cleanup_directory(dir_path: Path, root_boundary: Path | None = None) -> bool:
    """Safely delete an application-owned temporary directory."""
    boundary = (root_boundary or settings.STORAGE_DIR).resolve()
    target = dir_path.resolve()

    try:
        target.relative_to(boundary)
    except ValueError:
        raise StorageException(f"Refusing to delete path outside storage boundary: {dir_path}")

    if target.exists() and target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
        return True
    return False
