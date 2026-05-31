"""Unit tests for admin structured tag governance APIs."""

from contextlib import asynccontextmanager
import asyncio
import sqlite3

import aiosqlite
import pytest
from fastapi import HTTPException

import app.api.structured_tags as api
import app.rag.chunking.structured_tag_registry as registry
from app.api.structured_tags import StructuredTagUpdate
from app.core.auth import CurrentUser
from app.rag.chunking.structured_tag_registry import normalize_structured_tags


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def users():
    return {
        "admin": CurrentUser(user_id="u_admin", username="Admin", role="admin"),
        "user": CurrentUser(user_id="u_user", username="User", role="user"),
    }


@pytest.fixture
def tag_db(monkeypatch, tmp_path):
    db_path = tmp_path / "structured_tags.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """CREATE TABLE structured_tag_overrides (
                tag_key TEXT PRIMARY KEY,
                label TEXT,
                description TEXT,
                enabled INTEGER,
                ui_visible INTEGER,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        conn.commit()

    @asynccontextmanager
    async def _fake_get_db():
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = sqlite3.Row
            yield db

    monkeypatch.setattr(api, "get_db", _fake_get_db)
    monkeypatch.setattr(registry.settings, "DATABASE_PATH", str(db_path))
    registry.invalidate_structured_tag_overrides()
    yield db_path
    registry.invalidate_structured_tag_overrides()


def test_list_structured_tags_merges_overrides(tag_db, users):
    with sqlite3.connect(tag_db) as conn:
        conn.execute(
            """INSERT INTO structured_tag_overrides
               (tag_key, label, description, enabled, ui_visible)
               VALUES (?, ?, ?, ?, ?)""",
            ("approval_rule", "审批要求", "覆盖说明", 1, 0),
        )
        conn.commit()

    result = run(api.list_structured_tags(users["admin"]))
    records = {row["tag_key"]: row for row in result["records"]}

    assert result["total"] >= 1
    assert records["approval_rule"]["label"] == "审批要求"
    assert records["approval_rule"]["description"] == "覆盖说明"
    assert records["approval_rule"]["ui_visible"] is False
    assert records["approval_rule"]["overridden"] is True


def test_non_admin_is_forbidden(tag_db, users):
    with pytest.raises(HTTPException) as exc:
        run(api.list_structured_tags(users["user"]))

    assert exc.value.status_code == 403


def test_update_label_only_does_not_require_reindex(tag_db, users):
    result = run(api.update_structured_tag(
        "amount_threshold",
        StructuredTagUpdate(label="金额条件", ui_visible=False),
        users["admin"],
    ))

    assert result["record"]["label"] == "金额条件"
    assert result["record"]["ui_visible"] is False
    assert result["reindex_required"] is False


def test_update_enabled_affects_registry_and_requires_reindex(tag_db, users):
    assert normalize_structured_tags(["approval_rule"]) == ["approval_rule"]

    result = run(api.update_structured_tag(
        "approval_rule",
        StructuredTagUpdate(enabled=False),
        users["admin"],
    ))

    assert result["record"]["enabled"] is False
    assert result["reindex_required"] is True
    assert normalize_structured_tags(["approval_rule"]) == []


def test_reset_override_restores_default_and_reports_reindex(tag_db, users):
    run(api.update_structured_tag(
        "approval_rule",
        StructuredTagUpdate(enabled=False, label="审批要求"),
        users["admin"],
    ))

    result = run(api.reset_structured_tag("approval_rule", users["admin"]))

    assert result["record"]["enabled"] is True
    assert result["record"]["label"] == "审批规则"
    assert result["record"]["overridden"] is False
    assert result["reindex_required"] is True
    assert normalize_structured_tags(["approval_rule"]) == ["approval_rule"]


def test_unknown_tag_returns_404(tag_db, users):
    with pytest.raises(HTTPException) as exc:
        run(api.update_structured_tag(
            "unknown_tag",
            StructuredTagUpdate(label="未知"),
            users["admin"],
        ))

    assert exc.value.status_code == 404
