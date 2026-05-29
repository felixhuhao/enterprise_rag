"""Stable chunk key helpers."""

from __future__ import annotations

import hashlib
from collections.abc import MutableMapping


def normalize_chunk_content(content: object) -> str:
    """Normalize content for stable key hashing."""
    return " ".join(str(content or "").split())


def base_chunk_key(chunk: MutableMapping[str, object]) -> str:
    """Build the deterministic base key for one source chunk."""
    parts = [
        str(chunk.get("document_id") or ""),
        str(chunk.get("source_type") or ""),
        str(chunk.get("table_id") or ""),
        str(chunk.get("section_title") or ""),
        str(chunk.get("part") if chunk.get("part") is not None else ""),
        normalize_chunk_content(chunk.get("content")),
    ]
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]
    return f"ck_{digest}"


def assign_chunk_keys(chunks: list[MutableMapping[str, object]]) -> list[MutableMapping[str, object]]:
    """Assign stable chunk_key values, suffixing duplicate base keys deterministically."""
    seen: dict[str, int] = {}
    for chunk in chunks:
        key = str(chunk.get("chunk_key") or base_chunk_key(chunk))
        count = seen.get(key, 0) + 1
        seen[key] = count
        chunk["chunk_key"] = key if count == 1 else f"{key}_{count:02d}"
    return chunks
