"""API tests for auth + admin user/entity-ACL endpoints."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.api import admin_users as admin_api
from app.api import auth as auth_api
from app.core import auth as auth_core
from app.core import database
from app.core.auth import CurrentUser, hash_password
from app.deps import require_admin_user


def run(coro):
    return asyncio.run(coro)


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
    uploaded_by TEXT DEFAULT '',
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
def api_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "api_test.db")
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA_SQL)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO users (user_id, username, password_hash, created_at, role) VALUES (?, ?, ?, ?, ?)",
        ("u_admin", "Admin", hash_password("admin-demo-pass"), now, "admin"),
    )
    conn.execute(
        "INSERT INTO users (user_id, username, password_hash, created_at, role) VALUES (?, ?, ?, ?, ?)",
        ("u_alice", "Alice", hash_password("alice-demo-pass"), now, "user"),
    )
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('bootstrap_admin_user_id', 'u_admin')"
    )
    conn.execute(
        "INSERT INTO entity_acl (entity_name, user_id, permission) VALUES (?, ?, ?)",
        ("远景能源", "u_alice", "write"),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(database, "DB_PATH", db_path)
    return db_path


ADMIN = CurrentUser("u_admin", "Admin", "admin")
ALICE = CurrentUser("u_alice", "Alice", "user")


# --------------------------------------------------------------------------- #
# Login / Logout
# --------------------------------------------------------------------------- #

class TestLogin:
    def test_login_success(self, api_db):
        req = auth_api.LoginRequest(username="Alice", password="alice-demo-pass")
        result = run(auth_api.login(req))
        assert "token" in result
        assert result["user"]["username"] == "Alice"
        assert result["user"]["role"] == "user"
        assert "expires_at" in result

    def test_login_wrong_password(self, api_db):
        req = auth_api.LoginRequest(username="Alice", password="wrong")
        with pytest.raises(HTTPException) as exc:
            run(auth_api.login(req))
        assert exc.value.status_code == 401

    def test_login_unknown_user(self, api_db):
        req = auth_api.LoginRequest(username="Nobody", password="x" * 8)
        with pytest.raises(HTTPException) as exc:
            run(auth_api.login(req))
        assert exc.value.status_code == 401

    def test_logout_deletes_session(self, api_db):
        req = auth_api.LoginRequest(username="Alice", password="alice-demo-pass")
        result = run(auth_api.login(req))
        token = result["token"]
        assert run(auth_core.lookup_user(token)) is not None

        run(auth_api.logout(authorization=f"Bearer {token}"))
        assert run(auth_core.lookup_user(token)) is None


# --------------------------------------------------------------------------- #
# Admin user CRUD
# --------------------------------------------------------------------------- #

class TestUserCRUD:
    def test_create_user_success(self, api_db):
        req = admin_api.CreateUserRequest(username="newuser", password="password1234", role="user")
        result = run(admin_api.create_user(req, current_user=ADMIN))
        assert result["username"] == "newuser"
        assert result["role"] == "user"

    def test_create_user_duplicate_username(self, api_db):
        req = admin_api.CreateUserRequest(username="Alice", password="password1234", role="user")
        with pytest.raises(HTTPException) as exc:
            run(admin_api.create_user(req, current_user=ADMIN))
        assert exc.value.status_code == 409

    def test_create_user_short_password_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            admin_api.CreateUserRequest(username="x", password="short", role="user")

    def test_create_user_bad_role_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            admin_api.CreateUserRequest(username="x", password="password1234", role="superadmin")

    def test_list_users(self, api_db):
        result = run(admin_api.list_users(current_user=ADMIN))
        usernames = [u["username"] for u in result]
        assert "Admin" in usernames
        assert "Alice" in usernames

    def test_reset_password_invalidates_sessions(self, api_db):
        login_req = auth_api.LoginRequest(username="Alice", password="alice-demo-pass")
        login_result = run(auth_api.login(login_req))
        token = login_result["token"]
        assert run(auth_core.lookup_user(token)) is not None

        req = admin_api.ResetPasswordRequest(password="newpassword1234")
        run(admin_api.reset_password("u_alice", req, current_user=ADMIN))

        assert run(auth_core.lookup_user(token)) is None
        result = run(auth_api.login(auth_api.LoginRequest(username="Alice", password="newpassword1234")))
        assert result["user"]["username"] == "Alice"

    def test_delete_user(self, api_db):
        req = admin_api.CreateUserRequest(username="tempuser", password="password1234", role="user")
        created = run(admin_api.create_user(req, current_user=ADMIN))

        run(admin_api.delete_user(created["user_id"], current_user=ADMIN))

        users = run(admin_api.list_users(current_user=ADMIN))
        assert "tempuser" not in [u["username"] for u in users]

    def test_delete_last_admin_rejected(self, api_db):
        with pytest.raises(HTTPException) as exc:
            run(admin_api.delete_user("u_admin", current_user=ADMIN))
        assert exc.value.status_code == 409

    def test_delete_bootstrap_admin_rejected(self, api_db):
        req = admin_api.CreateUserRequest(username="admin2", password="password1234", role="admin")
        run(admin_api.create_user(req, current_user=ADMIN))

        with pytest.raises(HTTPException) as exc:
            run(admin_api.delete_user("u_admin", current_user=ADMIN))
        assert exc.value.status_code == 409

    def test_delete_second_admin_ok(self, api_db):
        req = admin_api.CreateUserRequest(username="admin2", password="password1234", role="admin")
        created = run(admin_api.create_user(req, current_user=ADMIN))

        result = run(admin_api.delete_user(created["user_id"], current_user=ADMIN))
        assert result["ok"] is True


# --------------------------------------------------------------------------- #
# Entity ACL management
# --------------------------------------------------------------------------- #

class TestEntityACL:
    def test_list_entities(self, api_db):
        conn = sqlite3.connect(api_db)
        conn.execute(
            "INSERT INTO general_documents (document_id, entity_name, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("doc1", "远景能源", "", ""),
        )
        conn.commit()
        conn.close()

        result = run(admin_api.list_entities(current_user=ADMIN))
        assert "远景能源" in result

    def test_grant_access(self, api_db):
        req = admin_api.GrantRequest(entity_name="中芯国际", user_id="u_alice", permission="read")
        result = run(admin_api.grant_access(req, current_user=ADMIN))
        assert result["ok"] is True

        conn = sqlite3.connect(api_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT permission FROM entity_acl WHERE entity_name = ? AND user_id = ?",
            ("中芯国际", "u_alice"),
        ).fetchone()
        conn.close()
        assert row["permission"] == "read"

    def test_grant_access_unknown_user(self, api_db):
        req = admin_api.GrantRequest(entity_name="中芯国际", user_id="nonexistent", permission="read")
        with pytest.raises(HTTPException) as exc:
            run(admin_api.grant_access(req, current_user=ADMIN))
        assert exc.value.status_code == 400

    def test_revoke_access(self, api_db):
        req = admin_api.RevokeRequest(entity_name="远景能源", user_id="u_alice")
        result = run(admin_api.revoke_access(req, current_user=ADMIN))
        assert result["ok"] is True

        conn = sqlite3.connect(api_db)
        count = conn.execute(
            "SELECT COUNT(*) FROM entity_acl WHERE entity_name = ? AND user_id = ?",
            ("远景能源", "u_alice"),
        ).fetchone()[0]
        conn.close()
        assert count == 0

    def test_entity_acl_overview(self, api_db):
        conn = sqlite3.connect(api_db)
        conn.execute(
            "INSERT INTO general_documents (document_id, entity_name, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("doc1", "远景能源", "", ""),
        )
        conn.commit()
        conn.close()

        result = run(admin_api.get_entity_acl_overview(current_user=ADMIN))
        entities = result["entities"]
        ent_names = [e["entity_name"] for e in entities]
        assert "远景能源" in ent_names
        ent = [e for e in entities if e["entity_name"] == "远景能源"][0]
        assert any(g["username"] == "Alice" for g in ent["grants"])


# --------------------------------------------------------------------------- #
# Non-admin blocked via require_admin_user dependency
# --------------------------------------------------------------------------- #

class TestNonAdminBlocked:
    def test_non_admin_rejected_by_dependency(self):
        """require_admin_user raises 403 for non-admin."""
        with pytest.raises(HTTPException) as exc:
            run(require_admin_user(current_user=ALICE))
        assert exc.value.status_code == 403

    def test_admin_accepted_by_dependency(self):
        """require_admin_user passes for admin."""
        result = run(require_admin_user(current_user=ADMIN))
        assert result.user_id == "u_admin"
