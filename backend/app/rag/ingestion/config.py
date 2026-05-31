"""Ingestion pipeline configuration."""

from dataclasses import dataclass

from langgraph.graph.state import RunnableConfig


@dataclass
class IngestionConfig:
    # Text chunking
    text_chunk_size: int = 1200
    text_chunk_overlap: int = 120

    # Table chunking
    table_full_token_limit: int = 2000
    table_group_hard_tokens: int = 1400
    table_group_max_rows: int = 10

    # Chunk search enrichment
    chunk_enrichment_enabled: bool = True
    chunk_enrichment_profile: str = "enterprise_policy"


def get_ingestion_config(config: RunnableConfig) -> IngestionConfig:
    """从 RunnableConfig 中提取 IngestionConfig，无则返回默认值。"""
    cfg = config.get("configurable", {}).get("ingestion_config")
    if cfg is None:
        return IngestionConfig()
    if isinstance(cfg, IngestionConfig):
        return cfg
    if isinstance(cfg, dict):
        valid = {k: v for k, v in cfg.items() if hasattr(IngestionConfig, k)}
        return IngestionConfig(**valid)
    return IngestionConfig()
