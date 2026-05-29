"""ACL/filter helpers — pure string utilities, no Milvus/LLM imports."""

from __future__ import annotations

from langgraph.graph.state import RunnableConfig


def escape_milvus_string(s: str) -> str:
    """Escape a string value for Milvus expr (backslash and double-quote)."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def build_acl_expr(ids: list[str]) -> str:
    """Build Milvus expr: document_id in ["id1", "id2", ...]."""
    escaped = [escape_milvus_string(id) for id in ids]
    return "document_id in [" + ", ".join(f'"{x}"' for x in escaped) + "]"


def build_entity_expr(entity_name: str) -> str:
    """Build Milvus expr: entity_name == "value" with escaping."""
    return f'entity_name == "{escape_milvus_string(entity_name)}"'


def combine_filters(*filters: str | None) -> str | None:
    """Combine multiple Milvus filter expressions with AND."""
    parts = [f for f in filters if f]
    return " and ".join(f"({f})" for f in parts) if parts else None


def get_allowed_ids(config: RunnableConfig) -> list[str] | None:
    """Read allowed_document_ids from request config. None = no restriction."""
    return config.get("configurable", {}).get("allowed_document_ids")
