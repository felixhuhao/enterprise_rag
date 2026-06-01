"""Document chunk query and normalization helpers."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from pathlib import Path

from app.config import settings
from app.rag.chunking.chunk_keys import base_chunk_key
from app.rag.query.metadata_utils import parse_json_list

logger = logging.getLogger(__name__)

QueryChunksFn = Callable[[str], list[dict]]
QueryChunkByKeyFn = Callable[[str, str], dict | None]
LoadParsedChunksFn = Callable[[str], list[dict]]
NormalizeChunkFn = Callable[[dict, str, int], dict]
SortChunksFn = Callable[[list[dict]], list[dict]]


async def get_document_chunks_payload(
    document_id: str,
    document: dict,
    *,
    query_milvus_chunks: QueryChunksFn,
    load_parsed_chunks: LoadParsedChunksFn,
    normalize_chunk: NormalizeChunkFn,
    sort_chunks: SortChunksFn,
) -> dict:
    """Return document metadata and normalized chunks from Milvus or parsed artifacts."""
    chunks_source = "none"
    chunks: list[dict] = []

    try:
        chunks = await asyncio.to_thread(query_milvus_chunks, document_id)
        if chunks:
            chunks_source = "milvus"
    except Exception:
        logger.warning("Failed to query Milvus chunks: document_id=%s", document_id, exc_info=True)

    if not chunks:
        chunks = load_parsed_chunks(document_id)
        if chunks:
            chunks_source = "parsed_artifact"

    return {
        "chunks_source": chunks_source,
        "document": document,
        "chunks": [
            normalize_chunk(row, document_id, idx)
            for idx, row in enumerate(sort_chunks(chunks), start=1)
        ],
    }


async def get_document_chunk_by_key_payload(
    document_id: str,
    chunk_key: str,
    *,
    query_milvus_chunk_by_key: QueryChunkByKeyFn,
    load_parsed_chunks: LoadParsedChunksFn,
    normalize_chunk: NormalizeChunkFn,
    sort_chunks: SortChunksFn,
) -> dict | None:
    """Return one normalized chunk by stable chunk_key from Milvus or parsed artifacts."""
    try:
        row = await asyncio.to_thread(query_milvus_chunk_by_key, document_id, chunk_key)
        if row:
            return normalize_chunk(row, document_id, 1)
    except Exception:
        logger.warning(
            "Failed to query Milvus chunk: document_id=%s chunk_key=%s",
            document_id,
            chunk_key,
            exc_info=True,
        )

    for idx, row in enumerate(sort_chunks(load_parsed_chunks(document_id)), start=1):
        chunk = normalize_chunk(row, document_id, idx)
        if chunk.get("chunk_key") == chunk_key:
            return chunk
    return None


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
