"""Unit tests for query-time entity alias matching."""

import sqlite3

from app.rag.query.config import QueryConfig
from app.rag.query.entity_confirm import entity_confirm_node


def _config(**kwargs):
    return {"configurable": {"query_config": QueryConfig(**kwargs)}}


def _patch_entities(monkeypatch, known=None, aliases=None):
    import app.rag.query.entity_cache as cache

    monkeypatch.setattr(cache, "get_known_entities", lambda: set(known or []))
    monkeypatch.setattr(cache, "get_alias_map", lambda: dict(aliases or {}))


def _run(query: str) -> dict:
    return entity_confirm_node({"query": query}, _config())


def test_exact_match_does_not_emit_alias_trace(monkeypatch):
    _patch_entities(
        monkeypatch,
        known={"星辰科技"},
        aliases={"星辰": ["星辰科技"]},
    )

    result = _run("星辰科技的差旅标准")

    assert result["entity_mode"] == "single"
    assert result["matched_entities"] == ["星辰科技"]
    assert result["alias_trace"] == []


def test_alias_routes_to_canonical_entity(monkeypatch):
    _patch_entities(
        monkeypatch,
        known={"星辰科技"},
        aliases={"星辰": ["星辰科技"]},
    )

    result = _run("星辰的差旅标准")

    assert result["entity_mode"] == "single"
    assert result["confirmed_entity"] == "星辰科技"
    assert result["entity_filter"] == 'entity_name == "星辰科技"'
    assert result["alias_trace"] == [
        {"alias": "星辰", "canonical": "星辰科技", "ambiguous": False}
    ]


def test_alias_match_is_case_insensitive(monkeypatch):
    _patch_entities(
        monkeypatch,
        known={"中芯国际"},
        aliases={"SMIC": ["中芯国际"]},
    )

    result = _run("smic 的报销制度")

    assert result["entity_mode"] == "single"
    assert result["confirmed_entity"] == "中芯国际"
    assert result["alias_trace"][0]["canonical"] == "中芯国际"


def test_ambiguous_alias_is_traced_but_not_used(monkeypatch):
    _patch_entities(
        monkeypatch,
        known={"星辰科技", "远景能源"},
        aliases={"科技": ["星辰科技", "远景能源"]},
    )

    result = _run("科技的制度")

    assert result["entity_mode"] == "none"
    assert result["matched_entities"] == []
    assert result["entity_filter"] == ""
    assert result["alias_trace"] == [
        {
            "alias": "科技",
            "canonicals": ["星辰科技", "远景能源"],
            "ambiguous": True,
        }
    ]


def test_exact_and_alias_can_coexist(monkeypatch):
    _patch_entities(
        monkeypatch,
        known={"星辰科技", "远景能源"},
        aliases={"远景": ["远景能源"]},
    )

    result = _run("星辰科技和远景的差旅标准")

    assert result["entity_mode"] == "multi_explicit"
    assert result["matched_entities"] == ["星辰科技", "远景能源"]
    assert result["alias_trace"][0]["canonical"] == "远景能源"


def test_multiple_aliases_to_same_canonical_are_deduped(monkeypatch):
    _patch_entities(
        monkeypatch,
        known={"星辰科技"},
        aliases={"星辰": ["星辰科技"], "Xingchen": ["星辰科技"]},
    )

    result = _run("星辰和Xingchen的政策")

    assert result["entity_mode"] == "single"
    assert result["matched_entities"] == ["星辰科技"]
    assert len(result["alias_trace"]) == 2


def test_no_exact_or_alias_falls_back_to_none(monkeypatch):
    _patch_entities(monkeypatch, known={"星辰科技"}, aliases={"星辰": ["星辰科技"]})

    result = _run("报销需要哪些材料")

    assert result["entity_mode"] == "none"
    assert result["matched_entities"] == []
    assert result["alias_trace"] == []


def test_alias_cache_reload_after_invalidate(monkeypatch, tmp_path):
    import app.rag.query.entity_cache as cache

    db_path = tmp_path / "aliases.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE entity_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alias TEXT NOT NULL,
                canonical_entity TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(alias, canonical_entity)
            )"""
        )
        conn.execute(
            "INSERT INTO entity_aliases (alias, canonical_entity) VALUES (?, ?)",
            ("星辰", "星辰科技"),
        )
        conn.commit()

    monkeypatch.setattr(cache.settings, "DATABASE_PATH", str(db_path))
    monkeypatch.setattr(cache.client, "query", lambda **_: [{"entity_name": "星辰科技"}])
    cache.invalidate()

    assert cache.get_alias_map() == {"星辰": ["星辰科技"]}

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO entity_aliases (alias, canonical_entity) VALUES (?, ?)",
            ("SMIC", "中芯国际"),
        )
        conn.commit()

    assert cache.get_alias_map() == {"星辰": ["星辰科技"]}
    cache.invalidate()
    assert cache.get_alias_map() == {"SMIC": ["中芯国际"], "星辰": ["星辰科技"]}
    cache.invalidate()
