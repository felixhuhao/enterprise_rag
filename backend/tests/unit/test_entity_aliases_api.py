"""Unit tests for admin entity alias CRUD handlers."""

from contextlib import asynccontextmanager
import asyncio
import sqlite3

import aiosqlite
import pytest
from fastapi import HTTPException

import app.api.entity_aliases as api
from app.api.entity_aliases import EntityAliasBatchItem, EntityAliasCreate
from app.core.auth import CurrentUser


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def users():
    return {
        "admin": CurrentUser(user_id="u_admin", username="Admin", role="admin"),
        "user": CurrentUser(user_id="u_user", username="User", role="user"),
    }


@pytest.fixture
def alias_db(monkeypatch, tmp_path):
    db_path = tmp_path / "aliases.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
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
        conn.commit()

    @asynccontextmanager
    async def _fake_get_db():
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = sqlite3.Row
            yield db

    invalidated = {"count": 0}
    monkeypatch.setattr(api, "get_db", _fake_get_db)
    monkeypatch.setattr(api, "get_known_entities", lambda: {"星辰科技", "中芯国际"})
    monkeypatch.setattr(api, "invalidate", lambda: invalidated.__setitem__("count", invalidated["count"] + 1))
    return invalidated


def test_create_list_and_delete_alias(alias_db, users):
    created = run(api.create_entity_alias(
        EntityAliasCreate(alias=" 星辰 ", canonical_entity=" 星辰科技 ", source="manual"),
        users["admin"],
    ))

    assert created["alias"] == "星辰"
    assert created["canonical_entity"] == "星辰科技"
    assert alias_db["count"] == 1

    listed = run(api.list_entity_aliases(current_user=users["admin"]))
    assert listed["total"] == 1
    assert listed["records"][0]["alias"] == "星辰"

    run(api.delete_entity_alias(created["id"], users["admin"]))
    assert alias_db["count"] == 2

    listed = run(api.list_entity_aliases(current_user=users["admin"]))
    assert listed["total"] == 0


def test_non_admin_is_forbidden(alias_db, users):
    with pytest.raises(HTTPException) as exc:
        run(api.list_entity_aliases(current_user=users["user"]))

    assert exc.value.status_code == 403


def test_unknown_canonical_is_rejected(alias_db, users):
    with pytest.raises(HTTPException) as exc:
        run(api.create_entity_alias(
            EntityAliasCreate(alias="未知", canonical_entity="未知公司"),
            users["admin"],
        ))

    assert exc.value.status_code == 400


def test_duplicate_create_returns_conflict(alias_db, users):
    body = EntityAliasCreate(alias="星辰", canonical_entity="星辰科技")
    run(api.create_entity_alias(body, users["admin"]))

    with pytest.raises(HTTPException) as exc:
        run(api.create_entity_alias(body, users["admin"]))

    assert exc.value.status_code == 409


def test_batch_create_counts_created_skipped_and_errors(alias_db, users):
    run(api.create_entity_alias(
        EntityAliasCreate(alias="星辰", canonical_entity="星辰科技"),
        users["admin"],
    ))

    result = run(api.batch_create_entity_aliases(
        [
            EntityAliasBatchItem(alias="星辰", canonical_entity="星辰科技"),
            EntityAliasBatchItem(alias="SMIC", canonical_entity="中芯国际"),
            EntityAliasBatchItem(alias="坏数据", canonical_entity="不存在"),
            EntityAliasBatchItem(alias=" ", canonical_entity="中芯国际"),
        ],
        users["admin"],
    ))

    assert result["created"] == 1
    assert result["skipped"] == 1
    assert [e["error"] for e in result["errors"]] == ["unknown_canonical", "empty_value"]
    assert alias_db["count"] == 2


def test_delete_missing_returns_404(alias_db, users):
    with pytest.raises(HTTPException) as exc:
        run(api.delete_entity_alias(999, users["admin"]))

    assert exc.value.status_code == 404
