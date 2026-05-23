"""Unified query configuration — parameters + feature toggles."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from langgraph.graph.state import RunnableConfig

logger = logging.getLogger(__name__)


@dataclass
class QueryConfig:
    # Feature toggles
    use_entity_confirm: bool = True
    use_rewrite: bool = True
    use_hyde: bool = True
    use_table_expand: bool = True
    use_rerank: bool = True

    # Search
    search_limit: int = 10
    dense_weight: float = 0.8
    sparse_weight: float = 0.2
    entity_filter_min_results: int = 3
    entity_filter_min_score: float = 0.6
    entity_filter_rerank_min_score: float = 0.5

    # HyDE
    hyde_limit: int = 10

    # RRF
    rrf_k: int = 60
    rrf_max_results: int = 20

    # Table expand
    table_full_token_limit: int = 2000
    table_medium_token_limit: int = 6000
    table_expand_limit: int = 20

    # Rerank
    rerank_batch_size: int = 10
    rerank_llm_weight: float = 0.7
    rerank_rrf_weight: float = 0.3
    rerank_max_top_k: int = 10
    rerank_min_top_k: int = 2
    rerank_cliff_threshold: float = 0.25
    rerank_fallback_score: float = 0.5

    # Content truncation (HyDE + rerank)
    content_preview_length: int = 300

    def __post_init__(self):
        self.clamp()

    def clamp(self):
        """Clamp numeric fields to safe ranges. Call after any bulk setattr."""
        _clamp(self, "search_limit", 1, 50)
        _clamp(self, "hyde_limit", 1, 50)
        _clamp(self, "rrf_k", 1, 200)
        _clamp(self, "rrf_max_results", 1, 50)
        _clamp(self, "table_expand_limit", 1, 50)
        _clamp(self, "table_full_token_limit", 50, 20000)
        _clamp(self, "table_medium_token_limit", 50, 20000)
        _clamp(self, "rerank_batch_size", 1, 20)
        _clamp(self, "rerank_max_top_k", 1, 30)
        _clamp(self, "rerank_min_top_k", 1, self.rerank_max_top_k)
        _clamp(self, "content_preview_length", 50, 2000)
        _clamp(self, "entity_filter_min_results", 1, 50)
        for name in ("dense_weight", "sparse_weight", "entity_filter_min_score",
                      "entity_filter_rerank_min_score", "rerank_llm_weight",
                      "rerank_rrf_weight", "rerank_cliff_threshold", "rerank_fallback_score"):
            _clamp(self, name, 0.0, 1.0)


def _clamp(cfg: QueryConfig, name: str, lo: float, hi: float):
    val = getattr(cfg, name)
    if val < lo:
        setattr(cfg, name, type(val)(lo))
    elif val > hi:
        setattr(cfg, name, type(val)(hi))


def get_query_config(config: RunnableConfig) -> QueryConfig:
    """从 RunnableConfig 中提取 QueryConfig，无则返回默认值。"""
    cfg = config.get("configurable", {}).get("query_config")
    if cfg is None:
        return get_default_query_config()
    if isinstance(cfg, QueryConfig):
        return cfg
    if isinstance(cfg, dict):
        valid = {k: v for k, v in cfg.items() if hasattr(QueryConfig, k)}
        return QueryConfig(**valid)
    return get_default_query_config()


def get_default_query_config() -> QueryConfig:
    """从 runtime_settings 构建默认 QueryConfig。"""
    from app.core.runtime_settings import runtime_settings

    cfg = QueryConfig()
    all_settings = runtime_settings.get_all_cached()
    for name, field in QueryConfig.__dataclass_fields__.items():
        raw = all_settings.get(f"query.{name}")
        if not raw:
            continue
        val = _cast_field(name, raw, field.type)
        if val is not None:
            setattr(cfg, name, val)
    cfg.clamp()
    return cfg


def _cast_field(name: str, raw: str, type_hint) -> Any:
    """将字符串值转为目标类型，非法值返回 None。"""
    # from __future__ import annotations makes type_hint a string
    type_map = {"bool": bool, "int": int, "float": float}
    resolved = type_map.get(type_hint) if isinstance(type_hint, str) else type_hint
    try:
        if resolved is bool:
            lowered = raw.lower()
            if lowered in ("true", "1", "yes", "on"):
                return True
            if lowered in ("false", "0", "no", "off"):
                return False
            return None
        if resolved is int:
            return int(raw)
        if resolved is float:
            return float(raw)
    except (ValueError, TypeError):
        logger.warning("Invalid settings value for query.%s: %r", name, raw)
    return None
