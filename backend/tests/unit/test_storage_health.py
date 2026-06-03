import os
from pathlib import Path

import pytest

from app.core import database, health


def test_validate_startup_storage_creates_required_dirs(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "app.db"
    upload_dir = tmp_path / "uploads"
    parsed_dir = tmp_path / "parsed"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    monkeypatch.setattr(health.settings, "GENERAL_UPLOAD_DIR", str(upload_dir))
    monkeypatch.setattr(health.settings, "GENERAL_PARSED_DIR", str(parsed_dir))
    monkeypatch.setattr(health.settings, "STORAGE_MIN_FREE_MB", 1)

    status = health.validate_startup_storage()

    assert db_path.parent.is_dir()
    assert upload_dir.is_dir()
    assert parsed_dir.is_dir()
    assert [item["label"] for item in status["directories"]] == ["database", "uploads", "parsed"]
    assert all(item["writable"] for item in status["directories"])
    assert status["disk"]["free_mb"] >= 0


def test_validate_startup_storage_fails_when_required_dir_is_file(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "app.db"
    upload_path = tmp_path / "not-a-dir"
    upload_path.write_text("file", encoding="utf-8")
    parsed_dir = tmp_path / "parsed"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    monkeypatch.setattr(health.settings, "GENERAL_UPLOAD_DIR", str(upload_path))
    monkeypatch.setattr(health.settings, "GENERAL_PARSED_DIR", str(parsed_dir))

    with pytest.raises(health.StorageStartupError, match="uploads"):
        health.validate_startup_storage()

    assert not Path(str(upload_path)).is_dir()


def test_validate_startup_storage_fails_when_required_dir_is_unwritable(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "app.db"
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    parsed_dir = tmp_path / "parsed"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    monkeypatch.setattr(health.settings, "GENERAL_UPLOAD_DIR", str(upload_dir))
    monkeypatch.setattr(health.settings, "GENERAL_PARSED_DIR", str(parsed_dir))

    upload_dir.chmod(0o555)
    try:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            pytest.skip("root can write to read-only directories")
        if os.access(upload_dir, os.W_OK):
            pytest.skip("filesystem permissions do not make the directory unwritable in this environment")
        with pytest.raises(health.StorageStartupError, match="uploads"):
            health.validate_startup_storage()
    finally:
        upload_dir.chmod(0o755)
