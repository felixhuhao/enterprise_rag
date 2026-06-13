"""
运行时设置模块

提供可动态修改的运行时配置，存储在 SQLite settings 表中。
使用内存缓存减少数据库查询，启动时一次性加载。
"""

from app.core.database import get_db

# 默认值（与 database.py 中的 seed 数据一致）
_DEFAULTS: dict[str, str] = {}


def _build_query_defaults() -> dict[str, str]:
    """从 QueryConfig dataclass 生成 query.* 默认值（懒加载避免循环 import）。"""
    from app.rag.query.config import QueryConfig

    defaults = {}
    for name, field in QueryConfig.__dataclass_fields__.items():
        defaults[f"query.{name}"] = str(field.default)
    return defaults


_DEFAULTS.update(_build_query_defaults())
_DEFAULTS.update(
    {
        "intent.inline_enabled": "true",
        "intent.active_mode": "true",
    }
)


class RuntimeSettings:
    """运行时设置读写器（SQLite + 内存缓存）"""

    def __init__(self):
        self._cache: dict[str, str] = {}
        self._loaded = False

    async def _ensure_loaded(self):
        if not self._loaded:
            await self._load_from_db()
            self._loaded = True

    async def _load_from_db(self):
        async with get_db() as db:
            async with db.execute("SELECT key, value FROM settings") as cursor:
                rows = await cursor.fetchall()
                self._cache = {row["key"]: row["value"] for row in rows}

    async def get(self, key: str) -> str:
        await self._ensure_loaded()
        return self._cache.get(key, _DEFAULTS.get(key, ""))

    async def get_float(self, key: str) -> float:
        return float(await self.get(key))

    async def get_int(self, key: str) -> int:
        return int(await self.get(key))

    async def set(self, key: str, value: str):
        async with get_db() as db:
            await db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
                (key, value, value),
            )
            await db.commit()
        self._cache[key] = value

    async def get_all(self) -> dict[str, str]:
        await self._ensure_loaded()
        # 合并默认值（防止数据库缺少某些 key）
        result = dict(_DEFAULTS)
        result.update(self._cache)
        return result

    def get_cached(self, key: str) -> str:
        """同步读取缓存值（不触发数据库查询，适用于同步路由函数）"""
        return self._cache.get(key, _DEFAULTS.get(key, ""))

    def get_all_cached(self) -> dict[str, str]:
        """同步读取所有缓存值（合并默认值）。"""
        result = dict(_DEFAULTS)
        result.update(self._cache)
        return result

    def get_cached_float(self, key: str) -> float:
        return float(self.get_cached(key))

    def get_cached_int(self, key: str) -> int:
        return int(self.get_cached(key))

    async def update_batch(self, updates: dict[str, str]):
        async with get_db() as db:
            for key, value in updates.items():
                await db.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
                    (key, value, value),
                )
                self._cache[key] = value
            await db.commit()


# 全局单例
runtime_settings = RuntimeSettings()
