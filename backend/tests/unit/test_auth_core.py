"""Unit tests for auth core: password hashing, sessions, entity ACL."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.core import auth, database
from app.core.auth import CurrentUser
from app.core import entity as entity_mod
from app.core.entity import canonicalize_with_map, canonicalize_entity_name, load_alias_map, normalize_entity_name


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

_SCHEMA_SQL = """
CREATE TABLE users (
    user_id       TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT,
    created_at    TEXT NOT NULL DEFAULT '',
    api_token     TEXT,
    role          TEXT DEFAULT 'user'
);
CREATE TABLE auth_sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);
CREATE TABLE entity_acl (
    entity_name TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    permission  TEXT NOT NULL,
    PRIMARY KEY (entity_name, user_id)
);
CREATE TABLE general_documents (
    document_id TEXT NOT NULL UNIQUE,
    entity_name TEXT DEFAULT '',
    filename    TEXT NOT NULL DEFAULT '',
    source_path TEXT NOT NULL DEFAULT '',
    file_type   TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'uploaded',
    created_at  TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL DEFAULT ''
);
CREATE TABLE entity_aliases (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    alias            TEXT NOT NULL,
    canonical_entity TEXT NOT NULL,
    source           TEXT NOT NULL DEFAULT 'manual',
    created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(alias, canonical_entity)
);
CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@pytest.fixture
def auth_db(tmp_path, monkeypatch):
    """Minimal auth DB — monkeypatch DB_PATH so get_db() hits the temp file."""
    db_path = str(tmp_path / "auth_test.db")
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA_SQL)
    conn.execute("INSERT INTO settings (key, value) VALUES ('bootstrap_admin_user_id', 'u_admin')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(database, "DB_PATH", db_path)
    return db_path


@pytest.fixture
def users(auth_db):
    """Insert Alice (user, write on 远景能源), Bob (user, read on 远景能源), Admin."""
    conn = sqlite3.connect(auth_db)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()
    for uid, uname, role in (
        ("u_alice", "Alice", "user"),
        ("u_bob", "Bob", "user"),
        ("u_admin", "Admin", "admin"),
    ):
        conn.execute(
            "INSERT INTO users (user_id, username, password_hash, created_at, role) "
            "VALUES (?, ?, ?, ?, ?)",
            (uid, uname, auth.hash_password("pass1234"), now, role),
        )
    conn.execute(
        "INSERT INTO entity_acl (entity_name, user_id, permission) VALUES (?, ?, ?)",
        ("远景能源", "u_alice", "write"),
    )
    conn.execute(
        "INSERT INTO entity_acl (entity_name, user_id, permission) VALUES (?, ?, ?)",
        ("远景能源", "u_bob", "read"),
    )
    conn.execute(
        "INSERT INTO general_documents (document_id, entity_name, created_at, updated_at) "
        "VALUES (?, ?, ?, ?)",
        ("doc1", "远景能源", now, now),
    )
    conn.execute(
        "INSERT INTO general_documents (document_id, entity_name, created_at, updated_at) "
        "VALUES (?, ?, ?, ?)",
        ("doc2", "远景能源", now, now),
    )
    conn.execute(
        "INSERT INTO general_documents (document_id, entity_name, created_at, updated_at) "
        "VALUES (?, ?, ?, ?)",
        ("doc3", "中芯国际", now, now),
    )
    conn.commit()
    conn.close()
    return {
        "alice": CurrentUser("u_alice", "Alice", "user"),
        "bob": CurrentUser("u_bob", "Bob", "user"),
        "admin": CurrentUser("u_admin", "Admin", "admin"),
        "outsider": CurrentUser("u_x", "X", "user"),
    }


# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #

class TestPasswordHashing:
    def test_hash_and_verify_roundtrip(self):
        h = auth.hash_password("s3cret-pass")
        assert h != "s3cret-pass"
        assert auth.verify_password("s3cret-pass", h) is True

    def test_verify_wrong_password(self):
        h = auth.hash_password("correct")
        assert auth.verify_password("wrong", h) is False

    def test_reject_over_72_bytes(self):
        long_pw = "x" * 73
        with pytest.raises(ValueError, match="72 bytes"):
            auth.hash_password(long_pw)

    def test_exactly_72_bytes_ok(self):
        pw = "x" * 72
        h = auth.hash_password(pw)
        assert auth.verify_password(pw, h) is True


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #

class TestSessions:
    def test_create_and_lookup(self, auth_db):
        conn = sqlite3.connect(auth_db)
        conn.execute(
            "INSERT INTO users (user_id, username, created_at, role) VALUES (?, ?, ?, ?)",
            ("u1", "u1", datetime.now(timezone.utc).isoformat(), "user"),
        )
        conn.commit()
        conn.close()

        raw_token, expires = run(auth.create_session("u1"))
        assert len(raw_token) > 20

        user = run(auth.lookup_user(raw_token))
        assert user is not None
        assert user.user_id == "u1"
        assert user.username == "u1"

    def test_lookup_expired_session(self, auth_db):
        conn = sqlite3.connect(auth_db)
        conn.execute(
            "INSERT INTO users (user_id, username, created_at, role) VALUES (?, ?, ?, ?)",
            ("u1", "u1", "", "user"),
        )
        # Insert an expired session directly
        token_hash = auth.hash_session_token("old-token")
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        conn.execute(
            "INSERT INTO auth_sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token_hash, "u1", past, past),
        )
        conn.commit()
        conn.close()

        user = run(auth.lookup_user("old-token"))
        assert user is None

    def test_delete_session(self, auth_db):
        conn = sqlite3.connect(auth_db)
        conn.execute(
            "INSERT INTO users (user_id, username, created_at, role) VALUES (?, ?, ?, ?)",
            ("u1", "u1", "", "user"),
        )
        conn.commit()
        conn.close()

        raw_token, _ = run(auth.create_session("u1"))
        assert run(auth.lookup_user(raw_token)) is not None

        run(auth.delete_session(raw_token))
        assert run(auth.lookup_user(raw_token)) is None

    def test_throttled_renewal(self, auth_db):
        """Session with expires_at > now+24h should NOT be renewed."""
        conn = sqlite3.connect(auth_db)
        conn.execute(
            "INSERT INTO users (user_id, username, created_at, role) VALUES (?, ?, ?, ?)",
            ("u1", "u1", "", "user"),
        )
        now = datetime.now(timezone.utc)
        # expires in 5 days — well above the 24h threshold
        future = (now + timedelta(days=5)).isoformat()
        token_hash = auth.hash_session_token("fresh-token")
        conn.execute(
            "INSERT INTO auth_sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token_hash, "u1", now.isoformat(), future),
        )
        conn.commit()
        conn.close()

        run(auth.touch_session(token_hash))

        conn = sqlite3.connect(auth_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT expires_at FROM auth_sessions WHERE token_hash = ?", (token_hash,)).fetchone()
        conn.close()
        # Should NOT have been renewed
        assert row["expires_at"] == future

    def test_throttled_renewal_triggers_when_close_to_expiry(self, auth_db):
        """Session with expires_at < now+24h SHOULD be renewed."""
        conn = sqlite3.connect(auth_db)
        conn.execute(
            "INSERT INTO users (user_id, username, created_at, role) VALUES (?, ?, ?, ?)",
            ("u1", "u1", "", "user"),
        )
        now = datetime.now(timezone.utc)
        # expires in 10 hours — below the 24h threshold
        near = (now + timedelta(hours=10)).isoformat()
        token_hash = auth.hash_session_token("expiring-token")
        conn.execute(
            "INSERT INTO auth_sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token_hash, "u1", now.isoformat(), near),
        )
        conn.commit()
        conn.close()

        run(auth.touch_session(token_hash))

        conn = sqlite3.connect(auth_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT expires_at FROM auth_sessions WHERE token_hash = ?", (token_hash,)).fetchone()
        conn.close()
        renewed = datetime.fromisoformat(row["expires_at"])
        # Should have been extended to ~7 days from now
        assert (renewed - now) > timedelta(days=6)


class TestPurgeExpired:
    def test_purge_deletes_only_expired(self, auth_db):
        conn = sqlite3.connect(auth_db)
        conn.execute(
            "INSERT INTO users (user_id, username, created_at, role) VALUES (?, ?, ?, ?)",
            ("u1", "u1", "", "user"),
        )
        now = datetime.now(timezone.utc)
        past = (now - timedelta(hours=1)).isoformat()
        future = (now + timedelta(days=5)).isoformat()
        conn.executemany(
            "INSERT INTO auth_sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            [
                ("h_expired", "u1", past, past),
                ("h_alive", "u1", now.isoformat(), future),
            ],
        )
        conn.commit()
        conn.close()

        deleted = run(auth.purge_expired_sessions("u1"))
        assert deleted == 1

        conn = sqlite3.connect(auth_db)
        remaining = conn.execute("SELECT token_hash FROM auth_sessions").fetchall()
        conn.close()
        assert len(remaining) == 1
        assert remaining[0][0] == "h_alive"


# --------------------------------------------------------------------------- #
# Bootstrap bypass
# --------------------------------------------------------------------------- #

class TestBootstrapBypass:
    def test_bootstrap_token_resolves_admin(self, auth_db, monkeypatch):
        conn = sqlite3.connect(auth_db)
        conn.execute(
            "INSERT INTO users (user_id, username, created_at, role) VALUES (?, ?, ?, ?)",
            ("u_admin", "Admin", "", "admin"),
        )
        conn.commit()
        conn.close()

        monkeypatch.setattr(auth.settings, "API_TOKEN", "my-bootstrap-token")

        user = run(auth.lookup_user("my-bootstrap-token"))
        assert user is not None
        assert user.user_id == "u_admin"
        assert user.role == "admin"

    def test_wrong_bootstrap_token_returns_none(self, auth_db, monkeypatch):
        monkeypatch.setattr(auth.settings, "API_TOKEN", "real-token")
        user = run(auth.lookup_user("wrong-token"))
        assert user is None


# --------------------------------------------------------------------------- #
# Entity ACL — get_allowed_document_ids
# --------------------------------------------------------------------------- #

class TestGetAllowedDocumentIds:
    def test_admin_returns_none(self, users):
        result = run(auth.get_allowed_document_ids(users["admin"]))
        assert result is None

    def test_write_user_sees_entity_docs(self, users):
        result = run(auth.get_allowed_document_ids(users["alice"]))
        assert result is not None
        assert set(result) == {"doc1", "doc2"}

    def test_read_user_sees_entity_docs(self, users):
        result = run(auth.get_allowed_document_ids(users["bob"]))
        assert result is not None
        assert set(result) == {"doc1", "doc2"}

    def test_no_grants_returns_empty_list(self, users):
        result = run(auth.get_allowed_document_ids(users["outsider"]))
        assert result == []


# --------------------------------------------------------------------------- #
# Entity ACL — has_permission
# --------------------------------------------------------------------------- #

class TestHasPermission:
    def test_admin_always_true(self, users):
        assert run(auth.has_permission(users["admin"], "doc1", "read")) is True
        assert run(auth.has_permission(users["admin"], "doc1", "write")) is True
        assert run(auth.has_permission(users["admin"], "doc3", "write")) is True

    def test_write_user_read_ok(self, users):
        assert run(auth.has_permission(users["alice"], "doc1", "read")) is True

    def test_write_user_write_ok(self, users):
        assert run(auth.has_permission(users["alice"], "doc1", "write")) is True

    def test_read_user_read_ok(self, users):
        assert run(auth.has_permission(users["bob"], "doc1", "read")) is True

    def test_read_user_write_denied(self, users):
        assert run(auth.has_permission(users["bob"], "doc1", "write")) is False

    def test_no_grants_denied(self, users):
        assert run(auth.has_permission(users["outsider"], "doc1", "read")) is False

    def test_owner_maps_to_write(self, users):
        """Legacy 'owner' callers map to 'write'."""
        assert run(auth.has_permission(users["alice"], "doc1", "owner")) is True
        assert run(auth.has_permission(users["bob"], "doc1", "owner")) is False

    def test_entity_name_arg_skips_doc_lookup(self, users):
        """When entity_name is provided, skip the document query."""
        assert run(
            auth.has_permission(users["alice"], "unknown-doc", "read", entity_name="远景能源")
        ) is True
        assert run(
            auth.has_permission(users["alice"], "unknown-doc", "read", entity_name="中芯国际")
        ) is False

    def test_nonexistent_doc_denied(self, users):
        assert run(auth.has_permission(users["alice"], "no-such-doc", "read")) is False


# --------------------------------------------------------------------------- #
# Entity ACL — grant / revoke
# --------------------------------------------------------------------------- #

class TestGrantRevoke:
    def test_grant_entity_success(self, auth_db):
        conn = sqlite3.connect(auth_db)
        conn.execute("INSERT INTO users (user_id, username, created_at) VALUES (?, ?, ?)", ("u1", "u1", ""))
        conn.commit()
        conn.close()

        ok = run(auth.grant_entity("星辰科技", "u1", "write"))
        assert ok is True

        conn = sqlite3.connect(auth_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT permission FROM entity_acl WHERE entity_name = ? AND user_id = ?",
            ("星辰科技", "u1"),
        ).fetchone()
        conn.close()
        assert row["permission"] == "write"

    def test_grant_rejects_blank_name(self, auth_db):
        conn = sqlite3.connect(auth_db)
        conn.execute("INSERT INTO users (user_id, username, created_at) VALUES (?, ?, ?)", ("u1", "u1", ""))
        conn.commit()
        conn.close()
        assert run(auth.grant_entity("", "u1", "read")) is False
        assert run(auth.grant_entity("  ", "u1", "read")) is False

    def test_grant_rejects_unknown_user(self, auth_db):
        assert run(auth.grant_entity("星辰科技", "nonexistent", "read")) is False

    def test_grant_rejects_bad_permission(self, auth_db):
        conn = sqlite3.connect(auth_db)
        conn.execute("INSERT INTO users (user_id, username, created_at) VALUES (?, ?, ?)", ("u1", "u1", ""))
        conn.commit()
        conn.close()
        assert run(auth.grant_entity("星辰科技", "u1", "owner")) is False
        assert run(auth.grant_entity("星辰科技", "u1", "delete")) is False

    def test_grant_normalizes_name(self, auth_db):
        conn = sqlite3.connect(auth_db)
        conn.execute("INSERT INTO users (user_id, username, created_at) VALUES (?, ?, ?)", ("u1", "u1", ""))
        conn.commit()
        conn.close()

        run(auth.grant_entity("  星辰科技  ", "u1", "read"))

        conn = sqlite3.connect(auth_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT entity_name FROM entity_acl WHERE user_id = ?", ("u1",)).fetchone()
        conn.close()
        assert row["entity_name"] == "星辰科技"

    def test_revoke_entity(self, auth_db):
        conn = sqlite3.connect(auth_db)
        conn.execute("INSERT INTO users (user_id, username, created_at) VALUES (?, ?, ?)", ("u1", "u1", ""))
        conn.execute(
            "INSERT INTO entity_acl (entity_name, user_id, permission) VALUES (?, ?, ?)",
            ("星辰科技", "u1", "read"),
        )
        conn.commit()
        conn.close()

        run(auth.revoke_entity("星辰科技", "u1"))

        conn = sqlite3.connect(auth_db)
        count = conn.execute("SELECT COUNT(*) FROM entity_acl WHERE user_id = ?", ("u1",)).fetchone()[0]
        conn.close()
        assert count == 0


# --------------------------------------------------------------------------- #
# Entity ACL — user_entities / can_write_entity
# --------------------------------------------------------------------------- #

class TestUserEntities:
    def test_write_user_entities(self, users):
        entities = run(auth.user_entities(users["alice"]))
        assert entities == ["远景能源"]

    def test_read_user_entities(self, users):
        entities = run(auth.user_entities(users["bob"], min_permission="read"))
        assert entities == ["远景能源"]

    def test_read_user_write_entities_empty(self, users):
        entities = run(auth.user_entities(users["bob"], min_permission="write"))
        assert entities == []

    def test_no_grants_empty(self, users):
        entities = run(auth.user_entities(users["outsider"]))
        assert entities == []


class TestCanWriteEntity:
    def test_admin_always_true(self, users):
        assert run(auth.can_write_entity(users["admin"], "anything")) is True

    def test_write_user_can_write(self, users):
        assert run(auth.can_write_entity(users["alice"], "远景能源")) is True

    def test_read_user_cannot_write(self, users):
        assert run(auth.can_write_entity(users["bob"], "远景能源")) is False

    def test_blank_entity_false(self, users):
        assert run(auth.can_write_entity(users["alice"], "")) is False

    def test_no_grants_false(self, users):
        assert run(auth.can_write_entity(users["outsider"], "远景能源")) is False


# --------------------------------------------------------------------------- #
# Canonicalization (entity.py)
# --------------------------------------------------------------------------- #

class TestNormalizeEntityName:
    def test_strip_whitespace(self):
        assert normalize_entity_name("  星辰  ") == "星辰"

    def test_none_returns_empty(self):
        assert normalize_entity_name(None) == ""

    def test_empty_returns_empty(self):
        assert normalize_entity_name("") == ""


class TestCanonicalization:
    def test_unambiguous_alias_canonicalized(self, auth_db):
        conn = sqlite3.connect(auth_db)
        conn.execute(
            "INSERT INTO entity_aliases (alias, canonical_entity) VALUES (?, ?)",
            ("远景", "远景能源"),
        )
        conn.commit()
        conn.close()

        async def _canon():
            async with database.get_db() as db:
                return await entity_mod.canonicalize_entity_name("远景", db)
        result = run(_canon())
        assert result == "远景能源"

    def test_ambiguous_alias_not_canonicalized(self, auth_db):
        conn = sqlite3.connect(auth_db)
        conn.executemany(
            "INSERT INTO entity_aliases (alias, canonical_entity) VALUES (?, ?)",
            [("SMIC", "中芯国际A"), ("SMIC", "中芯国际B")],
        )
        conn.commit()
        conn.close()

        async def _canon():
            async with database.get_db() as db:
                return await entity_mod.canonicalize_entity_name("SMIC", db)
        result = run(_canon())
        assert result == "SMIC"  # left as-is

    def test_unknown_value_not_canonicalized(self, auth_db):
        async def _canon():
            async with database.get_db() as db:
                return await entity_mod.canonicalize_entity_name("unknown", db)
        result = run(_canon())
        assert result == "unknown"

    def test_canonicalize_with_map_pure(self):
        alias_map = {"远景": ["远景能源"], "SMIC": ["A", "B"]}
        assert canonicalize_with_map("远景", alias_map) == "远景能源"
        assert canonicalize_with_map("SMIC", alias_map) == "SMIC"  # ambiguous
        assert canonicalize_with_map("unknown", alias_map) == "unknown"
        assert canonicalize_with_map("", alias_map) == ""
        assert canonicalize_with_map(None, alias_map) == ""


class TestNoAliasExpansionAtReadTime:
    """ACL checks use literal entity_name — no alias expansion."""

    def test_grant_on_canonical_does_not_cover_alias_stored_doc(self, auth_db):
        """A doc stored under alias '远景' is NOT covered by a grant on '远景能源'."""
        conn = sqlite3.connect(auth_db)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO users (user_id, username, created_at, role) VALUES (?, ?, ?, ?)",
            ("u1", "u1", now, "user"),
        )
        # Alias exists but doc is stored under the alias value
        conn.execute(
            "INSERT INTO entity_aliases (alias, canonical_entity) VALUES (?, ?)",
            ("远景", "远景能源"),
        )
        conn.execute(
            "INSERT INTO entity_acl (entity_name, user_id, permission) VALUES (?, ?, ?)",
            ("远景能源", "u1", "write"),
        )
        conn.execute(
            "INSERT INTO general_documents (document_id, entity_name, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("doc_alias", "远景", now, now),
        )
        conn.commit()
        conn.close()

        user = CurrentUser("u1", "u1", "user")
        # Doc stored under alias '远景', grant is on canonical '远景能源'
        assert run(auth.has_permission(user, "doc_alias", "read")) is False

        ids = run(auth.get_allowed_document_ids(user))
        assert ids == []  # no docs match the canonical entity_name

    def test_canonical_stored_doc_covered_by_grant(self, auth_db):
        """A doc stored under canonical '远景能源' IS covered by grant on '远景能源'."""
        conn = sqlite3.connect(auth_db)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO users (user_id, username, created_at, role) VALUES (?, ?, ?, ?)",
            ("u1", "u1", now, "user"),
        )
        conn.execute(
            "INSERT INTO entity_acl (entity_name, user_id, permission) VALUES (?, ?, ?)",
            ("远景能源", "u1", "write"),
        )
        conn.execute(
            "INSERT INTO general_documents (document_id, entity_name, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("doc_canon", "远景能源", now, now),
        )
        conn.commit()
        conn.close()

        user = CurrentUser("u1", "u1", "user")
        assert run(auth.has_permission(user, "doc_canon", "read")) is True
