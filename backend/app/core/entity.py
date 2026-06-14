"""Entity name normalization and alias canonicalization.

Shared by upload, rename, and migration so the unambiguous-alias rule is
applied consistently everywhere entity_name is written.
"""

from __future__ import annotations

import aiosqlite


def normalize_entity_name(entity_name: str | None) -> str:
    """Strip leading/trailing whitespace. Names remain case-sensitive."""
    return (entity_name or "").strip()


async def load_alias_map(db: aiosqlite.Connection) -> dict[str, list[str]]:
    """Return ``{alias: [canonical1, ...]}`` from the ``entity_aliases`` table.

    Both alias and canonical are normalized (stripped) before storage in the
    map, matching how they are stored in the DB (``api/entity_aliases.py``
    strips at insert time).
    """
    alias_map: dict[str, list[str]] = {}
    async with db.execute("SELECT alias, canonical_entity FROM entity_aliases") as cursor:
        rows = await cursor.fetchall()
    for row in rows:
        alias = normalize_entity_name(row["alias"])
        canonical = normalize_entity_name(row["canonical_entity"])
        if alias and canonical:
            bucket = alias_map.setdefault(alias, [])
            if canonical not in bucket:
                bucket.append(canonical)
    return alias_map


def canonicalize_with_map(entity_name: str | None, alias_map: dict[str, list[str]]) -> str:
    """Canonicalize using a preloaded alias map (bulk use).

    If *entity_name* matches an **unambiguous** alias (exactly one canonical),
    return the canonical name.  Otherwise return the normalized input as-is.
    Never guesses on ambiguous (>=2 canonicals) or unknown values.
    """
    normalized = normalize_entity_name(entity_name)
    if not normalized:
        return normalized
    canonicals = alias_map.get(normalized)
    if canonicals and len(canonicals) == 1:
        return canonicals[0]
    return normalized


async def canonicalize_entity_name(entity_name: str | None, db: aiosqlite.Connection) -> str:
    """Single-use canonicalization (loads the alias map each call).

    For bulk operations (migration), use :func:`load_alias_map` once and
    :func:`canonicalize_with_map` per row to avoid repeated queries.
    """
    alias_map = await load_alias_map(db)
    return canonicalize_with_map(entity_name, alias_map)
