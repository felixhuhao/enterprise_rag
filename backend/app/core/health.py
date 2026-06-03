"""Startup storage validation and health helpers."""

from __future__ import annotations

import logging
import secrets
import shutil
from pathlib import Path

from app.config import settings
from app.core import database

logger = logging.getLogger(__name__)


class StorageStartupError(RuntimeError):
    """Raised when required local storage is not usable at startup."""


def _resolve_dir(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _write_probe(directory: Path) -> None:
    probe = directory / f".startup-write-test-{secrets.token_hex(8)}"
    try:
        probe.write_bytes(b"ok")
    finally:
        try:
            probe.unlink()
        except FileNotFoundError:
            pass


def _check_writable_dir(label: str, path: str | Path) -> dict:
    directory = _resolve_dir(path)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if not directory.is_dir():
            raise NotADirectoryError(str(directory))
        _write_probe(directory)
    except Exception as exc:
        raise StorageStartupError(
            f"Storage directory is not writable: {label} path={directory} error={exc}"
        ) from exc
    return {"label": label, "path": str(directory), "writable": True}


def _disk_status(path: str | Path, min_free_mb: int) -> dict:
    directory = _resolve_dir(path)
    directory.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(directory)
    free_mb = usage.free // (1024 * 1024)
    warning = min_free_mb > 0 and free_mb < min_free_mb
    status = {
        "path": str(directory),
        "total_bytes": usage.total,
        "free_bytes": usage.free,
        "free_mb": free_mb,
        "min_free_mb": min_free_mb,
        "warning": warning,
    }
    if warning:
        logger.warning(
            "Low storage space for %s: free_mb=%s min_free_mb=%s",
            directory,
            free_mb,
            min_free_mb,
        )
    return status


def validate_startup_storage() -> dict:
    """Validate required local storage paths before serving requests."""
    database_dir = _resolve_dir(database.DB_PATH).parent
    directories = [
        _check_writable_dir("database", database_dir),
        _check_writable_dir("uploads", settings.GENERAL_UPLOAD_DIR),
        _check_writable_dir("parsed", settings.GENERAL_PARSED_DIR),
    ]
    disk = _disk_status(database_dir, int(settings.STORAGE_MIN_FREE_MB or 0))
    logger.info(
        "Storage validation complete database_dir=%s upload_dir=%s parsed_dir=%s free_mb=%s",
        directories[0]["path"],
        directories[1]["path"],
        directories[2]["path"],
        disk["free_mb"],
    )
    return {"directories": directories, "disk": disk}
