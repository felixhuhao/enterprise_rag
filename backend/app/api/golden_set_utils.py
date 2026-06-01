"""Shared helpers for golden-set JSONL files."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

_backend = Path(__file__).resolve().parents[2]
DATA_DIR = _backend / "data"
if not DATA_DIR.is_dir():
    DATA_DIR = _backend.parent / "data"

CHALLENGE_GOLDEN_SET_PATH = DATA_DIR / "challenge_golden_set_v1.jsonl"
LEGACY_GOLDEN_SET_PATH = DATA_DIR / "enterprise_docs_v1.jsonl"


def active_golden_set_path(*, create: bool = False) -> Path:
    if CHALLENGE_GOLDEN_SET_PATH.exists():
        return CHALLENGE_GOLDEN_SET_PATH
    if LEGACY_GOLDEN_SET_PATH.exists():
        return LEGACY_GOLDEN_SET_PATH
    if create:
        CHALLENGE_GOLDEN_SET_PATH.parent.mkdir(parents=True, exist_ok=True)
        return CHALLENGE_GOLDEN_SET_PATH
    raise FileNotFoundError(f"基准测试集不存在: {CHALLENGE_GOLDEN_SET_PATH}")


def boolish(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def load_jsonl(path: Path, *, skip_invalid: bool = False) -> list[dict]:
    if not path.is_file():
        return []
    items: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                if not skip_invalid:
                    raise
    return items


def write_jsonl_with_backup(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_name(f"{path.name}.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        shutil.copy2(path, backup)
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def append_jsonl_with_backup(path: Path, item: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_name(f"{path.name}.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        shutil.copy2(path, backup)
    needs_newline = path.exists() and path.stat().st_size > 0
    if needs_newline:
        with open(path, "rb") as existing:
            existing.seek(-1, 2)
            needs_newline = existing.read(1) != b"\n"
    with open(path, "a", encoding="utf-8") as f:
        if needs_newline:
            f.write("\n")
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
