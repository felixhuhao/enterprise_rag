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


@asynccontextmanager
async def get_db():
    """获取数据库连接的异步上下文管理器（每次新建，用完自动关闭）"""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
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
    status         TEXT NOT NULL DEFAULT 'uploaded',
    chunk_count    INTEGER DEFAULT 0,
    image_count    INTEGER DEFAULT 0,
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
    user_id          TEXT DEFAULT '',
    created_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_qrunstats_created ON query_run_stats(created_at);

CREATE TABLE IF NOT EXISTS users (
    user_id   TEXT PRIMARY KEY,
    username  TEXT NOT NULL,
    api_token TEXT NOT NULL UNIQUE,
    role      TEXT DEFAULT 'user'
);

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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
        # migration: 旧库可能没有 entity_name 列
        try:
            await db.execute("ALTER TABLE general_documents ADD COLUMN entity_name TEXT DEFAULT ''")
        except aiosqlite.OperationalError:
            pass  # 列已存在
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
        # Seed demo users (idempotent，admin token 同步 .env 配置)
        from app.config import settings as app_settings
        admin_token = app_settings.API_TOKEN.strip()
        if not admin_token:
            admin_token = secrets.token_urlsafe(32)
            app_settings.API_TOKEN = admin_token
            logger.warning("API_TOKEN is not configured; generated an ephemeral admin token for this process")
        for user_id, username, token, role in (
            ("u_alice", "Alice", "alice-demo-token", "user"),
            ("u_bob",   "Bob",   "bob-demo-token",   "user"),
            ("u_admin", "Admin", admin_token, "admin"),
        ):
            try:
                await db.execute(
                    "INSERT INTO users (user_id, username, api_token, role) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET api_token = excluded.api_token",
                    (user_id, username, token, role),
                )
            except Exception:
                pass
        # migration: QueryConfig 默认值 seed
        from app.core.runtime_settings import _DEFAULTS
        for key, value in _DEFAULTS.items():
            if key.startswith("query."):
                await db.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                    (key, value),
                )
        await db.commit()
    print(f"[启动] 数据库初始化完成: {DB_PATH}")
