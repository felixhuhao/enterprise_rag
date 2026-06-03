"""Deterministic chunk quality report generation."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

QUALITY_VERSION = "chunk_quality_v1"
PARSER_NAME = "markdown"
PARSER_VERSION = "markdown_v1"
CHUNKER_VERSION = "markdown_chunker_v1"

EMPTY_CHUNK = "empty_chunk"
LOW_INFORMATION_CHUNK = "low_information_chunk"
MISSING_SECTION_TITLE = "missing_section_title"
OVERSIZED_CHUNK = "oversized_chunk"
UNDERSIZED_CHUNK = "undersized_chunk"
DUPLICATE_CHUNK = "duplicate_chunk"
TABLE_WITHOUT_METADATA = "table_without_metadata"
IMAGE_WITHOUT_DESCRIPTION = "image_without_description"
IMAGE_WITHOUT_ASSET_PATH = "image_without_asset_path"

WARNING_TYPES = (
    EMPTY_CHUNK,
    LOW_INFORMATION_CHUNK,
    MISSING_SECTION_TITLE,
    OVERSIZED_CHUNK,
    UNDERSIZED_CHUNK,
    DUPLICATE_CHUNK,
    TABLE_WITHOUT_METADATA,
    IMAGE_WITHOUT_DESCRIPTION,
    IMAGE_WITHOUT_ASSET_PATH,
)

LOW_INFORMATION_CHARS = 30
UNDERSIZED_CHARS = 80
OVERSIZED_CHARS = 2500
LOW_INFORMATION_ALNUM_RATIO = 0.35

_IMAGE_DESCRIPTION_MARKERS = (
    "图片描述",
    "图像描述",
    "image description",
    "image:",
    "描述:",
)
_IMAGE_MARKDOWN_RE = re.compile(r"!\[[^\]]*]\(([^)]+)\)")
_WHITESPACE_RE = re.compile(r"\s+")


def build_chunk_quality_report(
    chunks: list[dict[str, Any]],
    *,
    document_id: str = "",
    parser_name: str = PARSER_NAME,
    parser_version: str = PARSER_VERSION,
    chunker_version: str = CHUNKER_VERSION,
    enrichment_profile: str = "",
    processed_at: str | None = None,
    source_file_type: str = "",
) -> dict[str, Any]:
    """Build a deterministic quality report for normalized chunk dictionaries."""
    processed_at = processed_at or datetime.now().isoformat()
    rows = [dict(chunk) for chunk in chunks if isinstance(chunk, dict)]
    duplicate_keys = _duplicate_content_keys(rows)
    annotated = [
        _chunk_report_item(chunk, index, duplicate_keys)
        for index, chunk in enumerate(rows, start=1)
    ]
    warning_counts = _warning_counts(annotated)
    lengths = [int(item["content_length"]) for item in annotated]

    metrics = {
        "min_chunk_chars": min(lengths) if lengths else 0,
        "max_chunk_chars": max(lengths) if lengths else 0,
        "avg_chunk_chars": round(sum(lengths) / len(lengths), 1) if lengths else 0,
        "empty_chunk_count": warning_counts.get(EMPTY_CHUNK, 0),
        "low_information_chunk_count": warning_counts.get(LOW_INFORMATION_CHUNK, 0),
        "missing_section_title_count": warning_counts.get(MISSING_SECTION_TITLE, 0),
        "oversized_chunk_count": warning_counts.get(OVERSIZED_CHUNK, 0),
        "undersized_chunk_count": warning_counts.get(UNDERSIZED_CHUNK, 0),
        "duplicate_chunk_count": warning_counts.get(DUPLICATE_CHUNK, 0),
        "table_without_metadata_count": warning_counts.get(TABLE_WITHOUT_METADATA, 0),
        "image_without_description_count": warning_counts.get(IMAGE_WITHOUT_DESCRIPTION, 0),
        "image_without_asset_path_count": warning_counts.get(IMAGE_WITHOUT_ASSET_PATH, 0),
    }

    return {
        "document_id": document_id,
        "status": "warning" if warning_counts else "good",
        "quality_version": QUALITY_VERSION,
        "parser_name": parser_name,
        "parser_version": parser_version,
        "chunker_version": chunker_version,
        "enrichment_profile": enrichment_profile,
        "processed_at": processed_at,
        "source_file_type": source_file_type,
        "chunk_count": len(annotated),
        "metrics": metrics,
        "warnings": [
            {"type": warning_type, "count": warning_counts[warning_type]}
            for warning_type in WARNING_TYPES
            if warning_counts.get(warning_type, 0) > 0
        ],
        "chunks": annotated,
    }


def unavailable_quality_report() -> dict[str, Any]:
    """Return the fixed report shape for documents without a quality artifact."""
    return {
        "status": "unavailable",
        "quality_version": "",
        "metrics": {},
        "warnings": [],
        "chunks": [],
    }


def failed_quality_report(
    *,
    document_id: str = "",
    error: str = "",
    parser_name: str = PARSER_NAME,
    parser_version: str = PARSER_VERSION,
    chunker_version: str = CHUNKER_VERSION,
    enrichment_profile: str = "",
    processed_at: str | None = None,
    source_file_type: str = "",
) -> dict[str, Any]:
    """Return a fixed report shape when analyzer execution fails."""
    return {
        "document_id": document_id,
        "status": "failed",
        "quality_version": QUALITY_VERSION,
        "parser_name": parser_name,
        "parser_version": parser_version,
        "chunker_version": chunker_version,
        "enrichment_profile": enrichment_profile,
        "processed_at": processed_at or datetime.now().isoformat(),
        "source_file_type": source_file_type,
        "chunk_count": 0,
        "metrics": {},
        "warnings": [],
        "chunks": [],
        "error": str(error)[:1000],
    }


def quality_summary(report: dict[str, Any]) -> dict[str, Any]:
    """Extract compact fields intended for document row persistence."""
    return {
        "quality_status": str(report.get("status") or "unavailable"),
        "quality_warning_count": sum(
            int(row.get("count") or 0)
            for row in report.get("warnings", [])
            if isinstance(row, dict)
        ),
        "parser_version": str(report.get("parser_version") or ""),
        "chunker_version": str(report.get("chunker_version") or ""),
        "enrichment_profile": str(report.get("enrichment_profile") or ""),
        "processed_at": str(report.get("processed_at") or ""),
    }


def _chunk_report_item(
    chunk: dict[str, Any],
    sequence: int,
    duplicate_keys: set[str],
) -> dict[str, Any]:
    content = str(chunk.get("content") or "")
    content_length = len(content)
    trimmed_length = len(content.strip())
    warnings: list[str] = []
    normalized_content = _normalize_content(content)

    if trimmed_length == 0:
        warnings.append(EMPTY_CHUNK)
    elif _is_low_information(content):
        warnings.append(LOW_INFORMATION_CHUNK)

    if not _has_section_title(chunk):
        warnings.append(MISSING_SECTION_TITLE)
    if trimmed_length > OVERSIZED_CHARS:
        warnings.append(OVERSIZED_CHUNK)
    if 0 < trimmed_length < UNDERSIZED_CHARS:
        warnings.append(UNDERSIZED_CHUNK)
    if normalized_content and normalized_content in duplicate_keys:
        warnings.append(DUPLICATE_CHUNK)
    if _is_table_chunk(chunk) and not _has_table_metadata(chunk):
        warnings.append(TABLE_WITHOUT_METADATA)
    if _image_paths(chunk):
        if not _has_image_description(chunk):
            warnings.append(IMAGE_WITHOUT_DESCRIPTION)
        if not _has_valid_image_asset_paths(chunk):
            warnings.append(IMAGE_WITHOUT_ASSET_PATH)

    return {
        "chunk_key": str(chunk.get("chunk_key") or ""),
        "sequence": sequence,
        "content_length": content_length,
        "warnings": warnings,
    }


def _warning_counts(chunks: list[dict[str, Any]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for chunk in chunks:
        counter.update(str(warning) for warning in chunk.get("warnings", []))
    return counter


def _duplicate_content_keys(chunks: list[dict[str, Any]]) -> set[str]:
    seen: dict[str, int] = defaultdict(int)
    for chunk in chunks:
        key = _normalize_content(chunk.get("content"))
        if key:
            seen[key] += 1
    return {key for key, count in seen.items() if count > 1}


def _normalize_content(value: Any) -> str:
    return _WHITESPACE_RE.sub(" ", str(value or "").strip()).lower()


def _is_low_information(content: str) -> bool:
    text = content.strip()
    if not text:
        return False
    if len(text) < LOW_INFORMATION_CHARS:
        return True
    alnum_count = sum(1 for char in text if char.isalnum())
    return (alnum_count / max(len(text), 1)) < LOW_INFORMATION_ALNUM_RATIO


def _has_section_title(chunk: dict[str, Any]) -> bool:
    return bool(str(chunk.get("section_title") or chunk.get("title") or "").strip())


def _is_table_chunk(chunk: dict[str, Any]) -> bool:
    source_type = str(chunk.get("source_type") or "").lower()
    return "table" in source_type


def _has_table_metadata(chunk: dict[str, Any]) -> bool:
    return any(
        str(chunk.get(field) or "").strip()
        for field in ("table_id", "table_title", "raw_table_path")
    )


def _image_paths(chunk: dict[str, Any]) -> list[str]:
    value = chunk.get("image_paths")
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    return []


def _has_image_description(chunk: dict[str, Any]) -> bool:
    for field in ("image_descriptions", "image_description", "image_caption"):
        value = chunk.get(field)
        if isinstance(value, dict) and value:
            return True
        if isinstance(value, list) and value:
            return True
        if isinstance(value, str) and value.strip():
            return True

    content = str(chunk.get("content") or "").lower()
    return any(marker in content for marker in _IMAGE_DESCRIPTION_MARKERS)


def _has_valid_image_asset_paths(chunk: dict[str, Any]) -> bool:
    paths = _image_paths(chunk)
    if not paths:
        return True
    for path in paths:
        stripped = path.strip()
        if not stripped:
            return False
        if stripped.startswith(("http://", "https://", "file://", "/")):
            return False
        if ".." in stripped.split("/"):
            return False
        if _IMAGE_MARKDOWN_RE.search(stripped):
            return False
    return True
