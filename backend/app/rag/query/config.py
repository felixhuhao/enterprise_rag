"""Unified query configuration — parameters + feature toggles."""

from __future__ import annotations

from dataclasses import dataclass

from langgraph.graph.state import RunnableConfig


@dataclass
class QueryConfig:
    # Feature toggles (opt-in，默认只跑 Step 1 基础管线)
    use_entity_confirm: bool = False
    use_rewrite: bool = True
    use_hyde: bool = False
    use_table_expand: bool = False
    use_rerank: bool = False

    # Search
    search_limit: int = 10
    dense_weight: float = 0.8
    sparse_weight: float = 0.2

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


def get_query_config(config: RunnableConfig) -> QueryConfig:
    """从 RunnableConfig 中提取 QueryConfig，无则返回默认值。"""
    cfg = config.get("configurable", {}).get("query_config")
    if cfg is None:
        return QueryConfig()
    if isinstance(cfg, QueryConfig):
        return cfg
    if isinstance(cfg, dict):
        valid = {k: v for k, v in cfg.items() if hasattr(QueryConfig, k)}
        return QueryConfig(**valid)
    return QueryConfig()
