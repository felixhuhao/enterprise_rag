"""Document chunk query and normalization helpers."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.config import settings
from app.rag.chunking.chunk_keys import base_chunk_key
from app.rag.query.metadata_utils import parse_json_list

logger = logging.getLogger(__name__)


def query_milvus_chunks(document_id: str) -> list[dict]:
    from app.rag.vectorstores.general_milvus import query_chunks_by_document_id

    return query_chunks_by_document_id(document_id)


def query_milvus_chunk_by_key(document_id: str, chunk_key: str) -> dict | None:
    from app.rag.vectorstores.general_milvus import query_chunk_by_key

    return query_chunk_by_key(document_id, chunk_key)


def load_parsed_chunks(document_id: str) -> list[dict]:
    chunks_path = Path(settings.GENERAL_PARSED_DIR) / document_id / "chunks.json"
    if not chunks_path.is_file():
        return []
    try:
        data = json.loads(chunks_path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to read parsed chunks: document_id=%s path=%s", document_id, chunks_path, exc_info=True)
        return []
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def normalize_chunk(row: dict, document_id: str, sequence_index: int) -> dict:
    image_paths = parse_json_list(row.get("image_paths"))
    keywords = parse_json_list(row.get("keywords"))
    structured_tags = parse_json_list(row.get("structured_tags"))

    content = row.get("content", "") or ""
    source_type = row.get("source_type", "text") or "text"
    part = row.get("part")
    row_for_key = {**row, "document_id": row.get("document_id") or document_id}
    chunk_key = row.get("chunk_key") or base_chunk_key(row_for_key)

    return {
        "chunk_key": chunk_key,
        "sequence": sequence_index,
        "milvus_chunk_id": row.get("chunk_id"),
        "document_id": row.get("document_id") or document_id,
        "file_title": row.get("file_title", ""),
        "entity_name": row.get("entity_name", ""),
        "content": content,
        "title": row.get("title", ""),
        "parent_title": row.get("parent_title", ""),
        "section_title": row.get("section_title", ""),
        "part": part,
        "page": row.get("page"),
        "source_type": source_type,
        "table_id": row.get("table_id"),
        "table_title": row.get("table_title"),
        "raw_table_path": row.get("raw_table_path"),
        "table_tokens": row.get("table_tokens"),
        "image_paths": image_paths,
        "keywords": keywords,
        "structured_tags": structured_tags,
        "content_length": len(content),
    }


def sort_chunks(chunks: list[dict]) -> list[dict]:
    def _key(row: dict):
        page = row.get("page")
        page_key = page if isinstance(page, int) else 10**9
        chunk_id = row.get("chunk_id")
        chunk_key = row.get("chunk_key") or ""
        id_key = chunk_id if isinstance(chunk_id, int) else 10**9
        return (page_key, chunk_key, id_key)

    return sorted(chunks, key=_key)
