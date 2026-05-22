"""
数据库管理模块

使用 aiosqlite 管理 SQLite 数据库连接，提供统一的初始化函数。
所有表在 init_db() 中创建，应用启动时调用。
"""

import os
from contextlib import asynccontextmanager

import aiosqlite

from app.config import settings

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
    error_msg      TEXT DEFAULT '',
    error_code     TEXT DEFAULT '',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
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
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_general_documents_status ON general_documents(status);
CREATE INDEX IF NOT EXISTS idx_general_documents_created ON general_documents(created_at);
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
    created_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_qrunstats_created ON query_run_stats(created_at);
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
        # migration: query_run_stats 耗时字段
        for col in ("retrieval_wall_ms", "first_token_ms", "generate_ms", "total_ms"):
            try:
                await db.execute(f"ALTER TABLE query_run_stats ADD COLUMN {col} INTEGER DEFAULT 0")
            except aiosqlite.OperationalError:
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
