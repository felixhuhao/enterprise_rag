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
CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    user_name   TEXT NOT NULL DEFAULT 'ZS',
    created_at  TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',
    title       TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS evaluate_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    input_text      TEXT DEFAULT '',
    score           REAL NOT NULL,
    from_web_search INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS knowledge_documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    filename    TEXT NOT NULL,
    source      TEXT NOT NULL UNIQUE,
    status      TEXT NOT NULL DEFAULT 'uploaded',
    doc_count   INTEGER DEFAULT 0,
    image_count INTEGER DEFAULT 0,
    error_msg   TEXT DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evaluate_session ON evaluate_records(session_id);
CREATE INDEX IF NOT EXISTS idx_evaluate_created ON evaluate_records(created_at);
CREATE INDEX IF NOT EXISTS idx_knowledge_status ON knowledge_documents(status);
"""

_DEFAULTS_SETTINGS = """
INSERT OR IGNORE INTO settings (key, value) VALUES
    ('evaluate_threshold_high', '0.8'),
    ('evaluate_threshold_low', '0.6'),
    ('retriever_top_k', '3'),
    ('default_user_name', 'ZS');
"""


async def init_db():
    """初始化数据库：创建目录、建表、插入默认数据"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.executescript(_DEFAULTS_SETTINGS)
        await db.commit()
    print(f"[启动] 数据库初始化完成: {DB_PATH}")
