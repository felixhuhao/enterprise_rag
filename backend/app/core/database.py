"""
数据库管理模块

使用 aiosqlite 管理 SQLite 数据库连接，提供统一的初始化函数。
所有表在 init_db() 中创建，应用启动时调用。
"""

import logging
import os
import secrets
from contextlib import asynccontextmanager

import aiosqlite

from app.config import settings

logger = logging.getLogger(__name__)

DB_PATH = settings.DATABASE_PATH

SQLITE_BUSY_TIMEOUT_MS = 5000
SQLITE_SYNCHRONOUS = "NORMAL"


async def _configure_connection(db: aiosqlite.Connection) -> None:
    """Apply connection-scoped SQLite pragmas.

    Database-level pragmas such as journal_mode are intentionally handled during
    startup initialization instead of on every short-lived connection.
    """
    await db.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    await db.execute("PRAGMA foreign_keys = ON")
    await db.execute(f"PRAGMA synchronous = {SQLITE_SYNCHRONOUS}")


async def open_db_connection() -> aiosqlite.Connection:
    """Open a short-lived SQLite connection with project defaults applied."""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await _configure_connection(db)
    return db


async def _pragma_value(db: aiosqlite.Connection, pragma: str):
    async with db.execute(f"PRAGMA {pragma}") as cursor:
        row = await cursor.fetchone()
    return row[0] if row else None


async def _enable_wal(db: aiosqlite.Connection) -> str:
    return str(await _pragma_value(db, "journal_mode = WAL")).lower()


async def sqlite_pragma_status() -> dict:
    """Return effective SQLite pragma values for startup logs and tests."""
    async with get_db() as db:
        return {
            "journal_mode": str(await _pragma_value(db, "journal_mode")).lower(),
            "busy_timeout": await _pragma_value(db, "busy_timeout"),
            "foreign_keys": await _pragma_value(db, "foreign_keys"),
            "synchronous": await _pragma_value(db, "synchronous"),
        }


@asynccontextmanager
async def get_db():
    """获取数据库连接的异步上下文管理器（每次新建，用完自动关闭）"""
    db = await open_db_connection()
    try:
        yield db
    finally:
        await db.close()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS general_documents (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id    TEXT NOT NULL UNIQUE,
    filename       TEXT NOT NULL,
    source_path    TEXT NOT NULL,
    file_type      TEXT NOT NULL,
    ingestion_mode TEXT NOT NULL DEFAULT 'text_only',
    entity_name    TEXT DEFAULT '',
    uploaded_by    TEXT DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'uploaded',
    chunk_count    INTEGER DEFAULT 0,
    image_count    INTEGER DEFAULT 0,
    quality_status TEXT DEFAULT 'unavailable',
    quality_warning_count INTEGER DEFAULT 0,
    parser_version TEXT DEFAULT '',
    chunker_version TEXT DEFAULT '',
    enrichment_profile TEXT DEFAULT '',
    processed_at   TEXT DEFAULT '',
    retry_count    INTEGER DEFAULT 0,
    last_failed_stage TEXT DEFAULT '',
    cleanup_status TEXT DEFAULT '',
    error_msg      TEXT DEFAULT '',
    error_code     TEXT DEFAULT '',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_error_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    stage       TEXT NOT NULL,
    error_code  TEXT NOT NULL,
    error_msg   TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS query_chat_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    citations   TEXT DEFAULT '[]',
    user_id     TEXT DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_general_documents_status ON general_documents(status);
CREATE INDEX IF NOT EXISTS idx_general_documents_created ON general_documents(created_at);
CREATE INDEX IF NOT EXISTS idx_error_events_doc ON document_error_events(document_id);
CREATE INDEX IF NOT EXISTS idx_qchat_session ON query_chat_messages(session_id);

CREATE TABLE IF NOT EXISTS query_run_stats (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       TEXT,
    query            TEXT,
    search_mode      TEXT DEFAULT '',
    search_mode_hyde TEXT DEFAULT '',
    result_count     INTEGER DEFAULT 0,
    rerank_avg_score REAL DEFAULT 0,
    rerank_top_score REAL DEFAULT 0,
    retrieval_wall_ms INTEGER DEFAULT 0,
    first_token_ms    INTEGER DEFAULT 0,
    generate_ms       INTEGER DEFAULT 0,
    total_ms          INTEGER DEFAULT 0,
    status           TEXT DEFAULT 'success',
    error_code       TEXT DEFAULT '',
    retrieved_chunks TEXT DEFAULT '[]',
    citations        TEXT DEFAULT '[]',
    retrieval_flavor TEXT DEFAULT 'balanced',
    strict_evidence  INTEGER DEFAULT 0,
    fallback_used    INTEGER DEFAULT 0,
    groundedness_score REAL DEFAULT NULL,
    endpoint         TEXT DEFAULT '',
    timings_json     TEXT DEFAULT '{}',
    settings_json    TEXT DEFAULT '{}',
    result_shape_json TEXT DEFAULT '{}',
    fallback_json    TEXT DEFAULT '{}',
    token_usage_json TEXT DEFAULT '{}',
    user_id          TEXT DEFAULT '',
    created_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_qrunstats_created ON query_run_stats(created_at);

CREATE TABLE IF NOT EXISTS users (
    user_id       TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT,
    created_at    TEXT NOT NULL DEFAULT '',
    api_token     TEXT,
    role          TEXT DEFAULT 'user'
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id);

CREATE TABLE IF NOT EXISTS entity_acl (
    entity_name TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    permission  TEXT NOT NULL,
    PRIMARY KEY (entity_name, user_id)
);
CREATE INDEX IF NOT EXISTS idx_entity_acl_user ON entity_acl(user_id);

CREATE TABLE IF NOT EXISTS document_acl (
    document_id TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    permission  TEXT NOT NULL DEFAULT 'read',
    PRIMARY KEY (document_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_acl_user ON document_acl(user_id);

CREATE TABLE IF NOT EXISTS query_feedback (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       TEXT NOT NULL,
    message_id       TEXT DEFAULT '',
    query            TEXT NOT NULL,
    answer           TEXT DEFAULT '',
    citations        TEXT DEFAULT '[]',
    retrieved_chunks TEXT DEFAULT '[]',
    rating           TEXT NOT NULL,
    comment          TEXT DEFAULT '',
    retrieval_flavor TEXT DEFAULT 'balanced',
    strict_evidence  INTEGER DEFAULT 0,
    user_id          TEXT DEFAULT '',
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_created ON query_feedback(created_at);
CREATE INDEX IF NOT EXISTS idx_feedback_user ON query_feedback(user_id);

CREATE TABLE IF NOT EXISTS jobs (
    job_id           TEXT PRIMARY KEY,
    job_type         TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'queued',
    resource_type    TEXT DEFAULT '',
    resource_id      TEXT DEFAULT '',
    progress_current INTEGER DEFAULT 0,
    progress_total   INTEGER DEFAULT 0,
    message          TEXT DEFAULT '',
    error_code       TEXT DEFAULT '',
    error_detail     TEXT DEFAULT '',
    attempt_count    INTEGER DEFAULT 1,
    created_by       TEXT DEFAULT '',
    created_at       TEXT NOT NULL,
    started_at       TEXT DEFAULT '',
    finished_at      TEXT DEFAULT '',
    updated_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status_updated ON jobs(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_jobs_type_updated ON jobs(job_type, updated_at);
CREATE INDEX IF NOT EXISTS idx_jobs_resource ON jobs(resource_type, resource_id);

CREATE TABLE IF NOT EXISTS entity_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alias TEXT NOT NULL,
    canonical_entity TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(alias, canonical_entity)
);
CREATE INDEX IF NOT EXISTS idx_aliases_alias ON entity_aliases(alias);
CREATE INDEX IF NOT EXISTS idx_aliases_canonical ON entity_aliases(canonical_entity);

CREATE TABLE IF NOT EXISTS structured_tag_overrides (
    tag_key TEXT PRIMARY KEY,
    label TEXT,
    description TEXT,
    enabled INTEGER,
    ui_visible INTEGER,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


async def init_db():
    """初始化数据库：创建目录、建表、插入默认数据"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = await open_db_connection()
    try:
        journal_mode = await _enable_wal(db)
        if journal_mode != "wal":
            logger.warning("SQLite WAL mode is not active for %s (journal_mode=%s)", DB_PATH, journal_mode)
        await db.executescript(_SCHEMA)
        # migration: 旧库可能没有 entity_name 列
        try:
            await db.execute("ALTER TABLE general_documents ADD COLUMN entity_name TEXT DEFAULT ''")
        except aiosqlite.OperationalError:
            pass  # 列已存在
        # migration: uploaded_by column (audit trail)
        try:
            await db.execute("ALTER TABLE general_documents ADD COLUMN uploaded_by TEXT DEFAULT ''")
        except aiosqlite.OperationalError:
            pass
        # index: entity_name (added after ALTER TABLE ensures the column exists)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_general_documents_entity ON general_documents(entity_name)"
        )
        # migration: error_code 列
        try:
            await db.execute("ALTER TABLE general_documents ADD COLUMN error_code TEXT DEFAULT ''")
        except aiosqlite.OperationalError:
            pass
        # migration: retry safety columns
        for _col, ddl in (
            ("retry_count", "ALTER TABLE general_documents ADD COLUMN retry_count INTEGER DEFAULT 0"),
            ("last_failed_stage", "ALTER TABLE general_documents ADD COLUMN last_failed_stage TEXT DEFAULT ''"),
            ("cleanup_status", "ALTER TABLE general_documents ADD COLUMN cleanup_status TEXT DEFAULT ''"),
        ):
            try:
                await db.execute(ddl)
            except aiosqlite.OperationalError:
                pass
        # migration: chunk quality summary columns
        for _col, ddl in (
            ("quality_status", "ALTER TABLE general_documents ADD COLUMN quality_status TEXT DEFAULT 'unavailable'"),
            ("quality_warning_count", "ALTER TABLE general_documents ADD COLUMN quality_warning_count INTEGER DEFAULT 0"),
            ("parser_version", "ALTER TABLE general_documents ADD COLUMN parser_version TEXT DEFAULT ''"),
            ("chunker_version", "ALTER TABLE general_documents ADD COLUMN chunker_version TEXT DEFAULT ''"),
            ("enrichment_profile", "ALTER TABLE general_documents ADD COLUMN enrichment_profile TEXT DEFAULT ''"),
            ("processed_at", "ALTER TABLE general_documents ADD COLUMN processed_at TEXT DEFAULT ''"),
        ):
            try:
                await db.execute(ddl)
            except aiosqlite.OperationalError:
                pass
        # migration: query_run_stats 耗时字段
        for col in ("retrieval_wall_ms", "first_token_ms", "generate_ms", "total_ms"):
            try:
                await db.execute(f"ALTER TABLE query_run_stats ADD COLUMN {col} INTEGER DEFAULT 0")
            except aiosqlite.OperationalError:
                pass
        # migration: query_run_stats status tracking
        for col_ddl in (
            "ALTER TABLE query_run_stats ADD COLUMN status TEXT DEFAULT 'success'",
            "ALTER TABLE query_run_stats ADD COLUMN error_code TEXT DEFAULT ''",
        ):
            try:
                await db.execute(col_ddl)
            except aiosqlite.OperationalError:
                pass
        # migration: retrieved_chunks JSON column on query_run_stats
        try:
            await db.execute("ALTER TABLE query_run_stats ADD COLUMN retrieved_chunks TEXT DEFAULT '[]'")
        except aiosqlite.OperationalError:
            pass
        # migration: query_run_stats flavor-aware metrics
        for col_ddl in (
            "ALTER TABLE query_run_stats ADD COLUMN citations TEXT DEFAULT '[]'",
            "ALTER TABLE query_run_stats ADD COLUMN retrieval_flavor TEXT DEFAULT 'balanced'",
            "ALTER TABLE query_run_stats ADD COLUMN strict_evidence INTEGER DEFAULT 0",
            "ALTER TABLE query_run_stats ADD COLUMN fallback_used INTEGER DEFAULT 0",
        ):
            try:
                await db.execute(col_ddl)
            except aiosqlite.OperationalError:
                pass
        # migration: groundedness_score column on query_run_stats
        try:
            await db.execute("ALTER TABLE query_run_stats ADD COLUMN groundedness_score REAL DEFAULT NULL")
        except aiosqlite.OperationalError:
            pass
        # migration: user_id column on query_run_stats
        try:
            await db.execute("ALTER TABLE query_run_stats ADD COLUMN user_id TEXT DEFAULT ''")
        except aiosqlite.OperationalError:
            pass
        # migration: query observability payload columns
        for col_ddl in (
            "ALTER TABLE query_run_stats ADD COLUMN endpoint TEXT DEFAULT ''",
            "ALTER TABLE query_run_stats ADD COLUMN timings_json TEXT DEFAULT '{}'",
            "ALTER TABLE query_run_stats ADD COLUMN settings_json TEXT DEFAULT '{}'",
            "ALTER TABLE query_run_stats ADD COLUMN result_shape_json TEXT DEFAULT '{}'",
            "ALTER TABLE query_run_stats ADD COLUMN fallback_json TEXT DEFAULT '{}'",
            "ALTER TABLE query_run_stats ADD COLUMN token_usage_json TEXT DEFAULT '{}'",
        ):
            try:
                await db.execute(col_ddl)
            except aiosqlite.OperationalError:
                pass
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_qrunstats_flavor_created "
            "ON query_run_stats(retrieval_flavor, created_at)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_qrunstats_user_flavor_created "
            "ON query_run_stats(user_id, retrieval_flavor, created_at)"
        )
        # migration: user_id column on query_chat_messages
        try:
            await db.execute("ALTER TABLE query_chat_messages ADD COLUMN user_id TEXT DEFAULT ''")
        except aiosqlite.OperationalError:
            pass
        # migration: feedback query config
        for col_ddl in (
            "ALTER TABLE query_feedback ADD COLUMN retrieval_flavor TEXT DEFAULT 'balanced'",
            "ALTER TABLE query_feedback ADD COLUMN strict_evidence INTEGER DEFAULT 0",
        ):
            try:
                await db.execute(col_ddl)
            except aiosqlite.OperationalError:
                pass
        await db.execute(
            """CREATE TABLE IF NOT EXISTS structured_tag_overrides (
                tag_key TEXT PRIMARY KEY,
                label TEXT,
                description TEXT,
                enabled INTEGER,
                ui_visible INTEGER,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        # migration: users table rebuild (old shape → password-hash shape)
        async with db.execute("PRAGMA table_info(users)") as _pragma:
            _user_cols = {row["name"] for row in await _pragma.fetchall()}
        if "password_hash" not in _user_cols:
            async with db.execute(
                "SELECT username, COUNT(*) as cnt FROM users GROUP BY username HAVING cnt > 1"
            ) as _dupe:
                _dupes = await _dupe.fetchall()
            if _dupes:
                _names = ", ".join(r["username"] for r in _dupes)
                raise RuntimeError(
                    f"Migration aborted: duplicate usernames ({_names}). "
                    "Resolve duplicates before proceeding."
                )
            await db.execute(
                "CREATE TABLE users_new ("
                "user_id TEXT PRIMARY KEY, "
                "username TEXT NOT NULL UNIQUE, "
                "password_hash TEXT, "
                "created_at TEXT NOT NULL DEFAULT '', "
                "api_token TEXT, "
                "role TEXT DEFAULT 'user')"
            )
            await db.execute(
                "INSERT INTO users_new (user_id, username, password_hash, created_at, api_token, role) "
                "SELECT user_id, username, NULL, '', api_token, role FROM users"
            )
            await db.execute("DROP TABLE users")
            await db.execute("ALTER TABLE users_new RENAME TO users")
            logger.info("users table rebuilt for password auth")

        # migration: normalize + canonicalize entity_name
        from app.core.entity import load_alias_map, canonicalize_with_map
        _alias_map = await load_alias_map(db)
        await db.execute(
            "UPDATE general_documents SET entity_name = TRIM(entity_name) "
            "WHERE entity_name != TRIM(entity_name)"
        )
        async with db.execute(
            "SELECT DISTINCT entity_name FROM general_documents WHERE entity_name != ''"
        ) as _ent:
            _distinct = [r["entity_name"] for r in await _ent.fetchall()]
        _canon: list[tuple[str, str]] = []
        for _ent_name in _distinct:
            _canonical = canonicalize_with_map(_ent_name, _alias_map)
            if _canonical != _ent_name:
                await db.execute(
                    "UPDATE general_documents SET entity_name = ? WHERE entity_name = ?",
                    (_canonical, _ent_name),
                )
                _canon.append((_ent_name, _canonical))
        if _canon:
            logger.info("entity_name canonicalized %d names: %s", len(_canon), _canon)
        _ambiguous: list[tuple[str, list[str], int]] = []
        for _ent_name in _distinct:
            _canon_list = _alias_map.get(_ent_name)
            if _canon_list and len(_canon_list) > 1:
                async with db.execute(
                    "SELECT COUNT(*) as cnt FROM general_documents WHERE entity_name = ?",
                    (_ent_name,),
                ) as _cnt:
                    _c = (await _cnt.fetchone())["cnt"]
                _ambiguous.append((_ent_name, _canon_list, _c))
        if _ambiguous:
            logger.warning("ambiguous alias-stored entity_names need admin resolution: %s", _ambiguous)
        async with db.execute(
            "SELECT COUNT(*) as cnt FROM general_documents WHERE entity_name = ''"
        ) as _blank:
            _blank_count = (await _blank.fetchone())["cnt"]
        if _blank_count:
            logger.warning(
                "%d documents have blank entity_name — admin-only until moved to a non-blank entity",
                _blank_count,
            )

        # migration: backfill entity_acl from document_acl (one-time)
        async with db.execute("SELECT COUNT(*) as cnt FROM entity_acl") as _ea:
            _ea_count = (await _ea.fetchone())["cnt"]
        if _ea_count == 0:
            await db.execute(
                "INSERT OR REPLACE INTO entity_acl (entity_name, user_id, permission) "
                "SELECT g.entity_name, d.user_id, "
                "  MAX(CASE WHEN d.permission = 'owner' THEN 'write' ELSE 'read' END) "
                "FROM document_acl d "
                "JOIN general_documents g ON d.document_id = g.document_id "
                "WHERE g.entity_name != '' "
                "GROUP BY g.entity_name, d.user_id"
            )
            async with db.execute("SELECT COUNT(*) as cnt FROM entity_acl") as _ea2:
                _backfilled = (await _ea2.fetchone())["cnt"]
            if _backfilled:
                logger.info("entity_acl backfilled from document_acl: %d grants", _backfilled)

        # Seed bootstrap_admin_user_id
        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('bootstrap_admin_user_id', 'u_admin')"
        )

        # Ensure API_TOKEN for bootstrap bypass (lookup_user reads this directly)
        from app.config import settings as app_settings
        if not app_settings.API_TOKEN.strip():
            app_settings.API_TOKEN = secrets.token_urlsafe(32)
            logger.warning("API_TOKEN is not configured; generated an ephemeral admin token for this process")

        # Seed demo users with passwords (first run; preserves existing passwords on restart)
        import bcrypt as _bcrypt
        from datetime import datetime as _dt, timezone as _tz
        _now = _dt.now(_tz.utc).isoformat()
        for _uid, _uname, _role, _pw in (
            ("u_alice", "Alice", "user", "alice-demo-pass"),
            ("u_bob",   "Bob",   "user", "bob-demo-pass"),
            ("u_admin", "Admin", "admin", "admin-demo-pass"),
        ):
            _pw_hash = _bcrypt.hashpw(_pw.encode(), _bcrypt.gensalt()).decode()
            await db.execute(
                "INSERT INTO users (user_id, username, password_hash, created_at, role) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "  password_hash = COALESCE(users.password_hash, excluded.password_hash)",
                (_uid, _uname, _pw_hash, _now, _role),
            )
        # migration: QueryConfig 默认值 seed
        from app.core.runtime_settings import _DEFAULTS
        for key, value in _DEFAULTS.items():
            if key.startswith("query."):
                await db.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                    (key, value),
                )
        await db.commit()
        busy_timeout = await _pragma_value(db, "busy_timeout")
        foreign_keys = await _pragma_value(db, "foreign_keys")
        synchronous = await _pragma_value(db, "synchronous")
    finally:
        await db.close()
    logger.info(
        "SQLite initialized path=%s journal_mode=%s busy_timeout=%s foreign_keys=%s synchronous=%s",
        DB_PATH,
        journal_mode,
        busy_timeout,
        foreign_keys,
        synchronous,
    )
    print(f"[启动] 数据库初始化完成: {DB_PATH}")
