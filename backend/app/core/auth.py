"""Authentication & authorization — password hashing, sessions, entity ACL."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import HTTPException

from app.config import settings
from app.core.database import get_db
from app.core.entity import normalize_entity_name

SESSION_TTL = timedelta(days=7)
RENEW_THRESHOLD = timedelta(hours=24)
MAX_PASSWORD_BYTES = 72


@dataclass
class CurrentUser:
    user_id: str
    username: str
    role: str  # 'user' | 'admin'


def require_admin(user: CurrentUser) -> None:
    """Pure checker — raises 403 if not admin.

    Call via ``deps.require_admin_user`` dependency; do NOT import
    ``verify_token`` here (would create a circular import with deps.py).
    """
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员")


# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #

def hash_password(password: str) -> str:
    """Hash a password with bcrypt. Rejects passwords >72 bytes."""
    pw_bytes = password.encode("utf-8")
    if len(pw_bytes) > MAX_PASSWORD_BYTES:
        raise ValueError("Password exceeds 72 bytes (bcrypt limit)")
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# Session management
# --------------------------------------------------------------------------- #

def hash_session_token(token: str) -> str:
    """SHA-256 hash of a session token for DB storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_session(user_id: str) -> tuple[str, str]:
    """Create a new session for *user_id*.

    Returns ``(raw_token, expires_at_iso)``.  The raw token is returned only
    here — the DB stores ``hash_session_token(raw_token)``.  Also purges
    expired sessions for this user as part of the login flow.
    """
    await purge_expired_sessions(user_id)
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_session_token(raw_token)
    now = datetime.now(timezone.utc)
    expires_at = now + SESSION_TTL
    async with get_db() as db:
        await db.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (token_hash, user_id, now.isoformat(), expires_at.isoformat()),
        )
        await db.commit()
    return raw_token, expires_at.isoformat()


async def delete_session(token: str) -> None:
    """Delete the session matching *token* (logout)."""
    token_hash = hash_session_token(token)
    async with get_db() as db:
        await db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
        await db.commit()


async def touch_session(token_hash: str) -> None:
    """Throttled sliding renewal — only extend when ``expires_at < now + 24h``."""
    now = datetime.now(timezone.utc)
    threshold = (now + RENEW_THRESHOLD).isoformat()
    new_expires = (now + SESSION_TTL).isoformat()
    async with get_db() as db:
        await db.execute(
            "UPDATE sessions SET expires_at = ? "
            "WHERE token_hash = ? AND expires_at < ?",
            (new_expires, token_hash, threshold),
        )
        await db.commit()


async def purge_expired_sessions(user_id: str | None = None) -> int:
    """Delete expired sessions.  If *user_id* given, scope to that user."""
    now_iso = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        if user_id:
            cursor = await db.execute(
                "DELETE FROM sessions WHERE expires_at < ? AND user_id = ?",
                (now_iso, user_id),
            )
        else:
            cursor = await db.execute(
                "DELETE FROM sessions WHERE expires_at < ?", (now_iso,)
            )
        await db.commit()
        return cursor.rowcount


# --------------------------------------------------------------------------- #
# Token / user lookup
# --------------------------------------------------------------------------- #

async def get_bootstrap_admin_id() -> str:
    """Read ``bootstrap_admin_user_id`` from settings (default ``u_admin``)."""
    async with get_db() as db:
        async with db.execute(
            "SELECT value FROM settings WHERE key = 'bootstrap_admin_user_id'"
        ) as cursor:
            row = await cursor.fetchone()
    return row["value"] if row else "u_admin"


async def lookup_user(token: str) -> CurrentUser | None:
    """Resolve a Bearer token to a :class:`CurrentUser`.

    * **Bootstrap bypass**: if *token* matches ``.env API_TOKEN``, return the
      bootstrap admin row.
    * **Session path**: hash *token*, join ``sessions``, reject expired,
      throttled-renew.
    """
    if not token:
        return None

    # Bootstrap bypass
    api_token = settings.API_TOKEN.strip()
    if api_token and token == api_token:
        admin_id = await get_bootstrap_admin_id()
        async with get_db() as db:
            async with db.execute(
                "SELECT user_id, username, role FROM users WHERE user_id = ?",
                (admin_id,),
            ) as cursor:
                row = await cursor.fetchone()
        if row:
            return CurrentUser(
                user_id=row["user_id"],
                username=row["username"],
                role=row["role"],
            )
        return None

    # Session lookup
    token_hash = hash_session_token(token)
    now = datetime.now(timezone.utc)
    async with get_db() as db:
        async with db.execute(
            "SELECT s.token_hash, s.user_id, s.expires_at, u.username, u.role "
            "FROM sessions s JOIN users u ON s.user_id = u.user_id "
            "WHERE s.token_hash = ?",
            (token_hash,),
        ) as cursor:
            row = await cursor.fetchone()
    if not row:
        return None

    expires = datetime.fromisoformat(row["expires_at"])
    if expires <= now:
        return None

    await touch_session(row["token_hash"])

    return CurrentUser(
        user_id=row["user_id"],
        username=row["username"],
        role=row["role"],
    )


# --------------------------------------------------------------------------- #
# Entity ACL
# --------------------------------------------------------------------------- #

async def get_allowed_document_ids(user: CurrentUser) -> list[str] | None:
    """Document IDs the user can read.

    * ``None`` → admin (no restriction).
    * ``[]``   → user with no grants (see nothing).
    * list     → IDs of documents in entities the user can read.
    """
    if user.role == "admin":
        return None

    entities = await user_entities(user, min_permission="read")
    if not entities:
        return []

    placeholders = ", ".join("?" for _ in entities)
    async with get_db() as db:
        async with db.execute(
            f"SELECT document_id FROM general_documents "
            f"WHERE entity_name IN ({placeholders})",
            entities,
        ) as cursor:
            rows = await cursor.fetchall()
    return [r["document_id"] for r in rows]


async def has_permission(
    user: CurrentUser,
    document_id: str,
    min_permission: str,
    entity_name: str | None = None,
) -> bool:
    """Check minimum permission on a document via entity ACL.

    ``'read'`` satisfied by ``read|write``; ``'write'`` requires ``'write'``.
    ``'owner'`` callers are mapped to ``'write'``.  Admin always ``True``.
    """
    if user.role == "admin":
        return True

    if min_permission == "owner":
        min_permission = "write"

    if entity_name is None:
        async with get_db() as db:
            async with db.execute(
                "SELECT entity_name FROM general_documents WHERE document_id = ?",
                (document_id,),
            ) as cursor:
                row = await cursor.fetchone()
        if not row:
            return False
        entity_name = row["entity_name"]

    if not entity_name:
        return False

    if min_permission == "read":
        sql = (
            "SELECT 1 FROM entity_acl WHERE entity_name = ? AND user_id = ? "
            "AND permission IN ('read', 'write')"
        )
    else:
        sql = (
            "SELECT 1 FROM entity_acl WHERE entity_name = ? AND user_id = ? "
            "AND permission = 'write'"
        )

    async with get_db() as db:
        async with db.execute(sql, (entity_name, user.user_id)) as cursor:
            row = await cursor.fetchone()
    return row is not None


async def user_entities(user: CurrentUser, min_permission: str = "read") -> list[str]:
    """Entity names the user has at least *min_permission* on.

    Literal ``entity_name`` comparison only — no alias expansion.
    """
    if user.role == "admin":
        async with get_db() as db:
            async with db.execute(
                "SELECT DISTINCT entity_name FROM general_documents WHERE entity_name != '' "
                "UNION SELECT DISTINCT entity_name FROM entity_acl"
            ) as cursor:
                rows = await cursor.fetchall()
        return [r["entity_name"] for r in rows]

    if min_permission == "read":
        sql = (
            "SELECT DISTINCT entity_name FROM entity_acl "
            "WHERE user_id = ? AND permission IN ('read', 'write')"
        )
    else:
        sql = (
            "SELECT DISTINCT entity_name FROM entity_acl "
            "WHERE user_id = ? AND permission = 'write'"
        )
    async with get_db() as db:
        async with db.execute(sql, (user.user_id,)) as cursor:
            rows = await cursor.fetchall()
    return [r["entity_name"] for r in rows]


async def can_write_entity(user: CurrentUser, entity_name: str) -> bool:
    """Whether *user* has write on *entity_name*. Admin always ``True``."""
    if user.role == "admin":
        return True
    normalized = normalize_entity_name(entity_name)
    if not normalized:
        return False
    async with get_db() as db:
        async with db.execute(
            "SELECT 1 FROM entity_acl "
            "WHERE entity_name = ? AND user_id = ? AND permission = 'write'",
            (normalized, user.user_id),
        ) as cursor:
            row = await cursor.fetchone()
    return row is not None


async def grant_entity(entity_name: str, user_id: str, permission: str) -> bool:
    """Grant entity access.

    Rejects blank names, unknown users, and invalid permissions.
    Returns ``True`` on success.
    """
    normalized = normalize_entity_name(entity_name)
    if not normalized or permission not in ("read", "write"):
        return False
    async with get_db() as db:
        async with db.execute(
            "SELECT 1 FROM users WHERE user_id = ?", (user_id,)
        ) as cursor:
            if not await cursor.fetchone():
                return False
        await db.execute(
            "INSERT OR REPLACE INTO entity_acl (entity_name, user_id, permission) "
            "VALUES (?, ?, ?)",
            (normalized, user_id, permission),
        )
        await db.commit()
    return True


async def revoke_entity(entity_name: str, user_id: str) -> None:
    """Revoke entity access for a user."""
    normalized = normalize_entity_name(entity_name)
    async with get_db() as db:
        await db.execute(
            "DELETE FROM entity_acl WHERE entity_name = ? AND user_id = ?",
            (normalized, user_id),
        )
        await db.commit()
