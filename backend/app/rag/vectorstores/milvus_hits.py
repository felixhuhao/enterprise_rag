"""Helpers for converting Milvus hits into retrieval result rows."""

from __future__ import annotations

from app.rag.chunking.chunk_keys import base_chunk_key
from app.rag.query.metadata_utils import parse_json_list


def fallback_chunk_key(row: dict) -> str:
    return base_chunk_key({
        "document_id": row.get("document_id", ""),
        "source_type": row.get("source_type", ""),
        "table_id": row.get("table_id", ""),
        "section_title": row.get("section_title", ""),
        "part": row.get("part"),
        "content": row.get("content", ""),
    })


def parse_hits(hits, *, include_image_paths: bool = False) -> list[dict]:
    out = []
    for hit in hits:
        entity = hit["entity"]
        chunk_id = hit.get("id") or hit.get("chunk_id") or entity.get("chunk_id")
        row = {
            "chunk_id": chunk_id,
            "chunk_key": entity.get("chunk_key") or fallback_chunk_key(entity),
            "document_id": entity.get("document_id", ""),
            "page": entity.get("page"),
            "file_title": entity.get("file_title", ""),
            "entity_name": entity.get("entity_name", ""),
            "title": entity.get("title", ""),
            "section_title": entity.get("section_title", ""),
            "source_type": entity.get("source_type", ""),
            "table_id": entity.get("table_id", ""),
            "table_title": entity.get("table_title", ""),
            "table_tokens": entity.get("table_tokens"),
            "raw_table_path": entity.get("raw_table_path", ""),
            "content": entity.get("content", ""),
            "keywords": parse_json_list(entity.get("keywords")),
            "structured_tags": parse_json_list(entity.get("structured_tags")),
            "part": entity.get("part"),
            "score": hit["distance"],
        }
        if include_image_paths:
            row["image_paths"] = parse_json_list(entity.get("image_paths"))
        out.append(row)
    return out
