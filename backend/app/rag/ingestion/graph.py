"""LangGraph-based ingestion workflow.

Deterministic state machine:
entry → route → parse/read → normalize → chunk → enrich_search_metadata → embed_and_save.
No checkpointing, no agent loops.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from typing import Callable, TypedDict

from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.graph.state import RunnableConfig

from app.config import settings
from app.rag.ingestion.chunk_quality import (
    CHUNKER_VERSION,
    build_chunk_quality_report,
    failed_quality_report,
    quality_summary,
)
from app.rag.ingestion.service import extract_entity_name


PARSER_VERSIONS = {
    "pdf": ("mineru", "mineru_v1"),
    "md": ("markdown", "markdown_v1"),
    "md_zip": ("markdown_zip", "markdown_zip_v1"),
}


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class IngestionState(TypedDict, total=False):
    # 输入
    document_id: str
    filename: str
    file_type: str  # "pdf" | "md"
    source_path: str

    # 中间产物
    entity_name: str
    parsed_dir: str
    markdown: str
    image_count: int
    images_dir: str
    image_descriptions: dict
    chunks: list[dict]
    embedded_chunks: list[dict]
    quality_report: dict

    # 状态追踪
    status: str
    chunk_count: int
    error_msg: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_parsed_dir(parsed_dir: str):
    if os.path.isdir(parsed_dir):
        shutil.rmtree(parsed_dir)
    os.makedirs(parsed_dir, exist_ok=True)


def _count_images(images_dir: str | None) -> int:
    if not images_dir or not os.path.isdir(images_dir):
        return 0
    return sum(
        1
        for name in os.listdir(images_dir)
        if os.path.splitext(name)[1].lower() in {".png", ".jpg", ".jpeg", ".webp"}
    )


def _get_updater(config: RunnableConfig) -> Callable | None:
    return config.get("configurable", {}).get("status_updater")


def _write_json_artifact(path: str, data: object) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _write_chunks_artifact(parsed_dir: str, chunks: list[dict]) -> None:
    _write_json_artifact(os.path.join(parsed_dir, "chunks.json"), chunks)


def _parser_metadata(file_type: str) -> tuple[str, str]:
    return PARSER_VERSIONS.get(file_type, ("markdown", "markdown_v1"))


def _build_quality_report(state: IngestionState, config: RunnableConfig, chunks: list[dict]) -> dict:
    from app.rag.ingestion.config import get_ingestion_config

    cfg = get_ingestion_config(config)
    processed_at = datetime.now().isoformat()
    parser_name, parser_version = _parser_metadata(state.get("file_type", ""))
    try:
        return build_chunk_quality_report(
            chunks,
            document_id=state["document_id"],
            parser_name=parser_name,
            parser_version=parser_version,
            chunker_version=CHUNKER_VERSION,
            enrichment_profile=cfg.chunk_enrichment_profile if cfg.chunk_enrichment_enabled else "none",
            processed_at=processed_at,
            source_file_type=state.get("file_type", ""),
        )
    except Exception as exc:
        return failed_quality_report(
            document_id=state.get("document_id", ""),
            error=str(exc),
            parser_name=parser_name,
            parser_version=parser_version,
            chunker_version=CHUNKER_VERSION,
            enrichment_profile=cfg.chunk_enrichment_profile if cfg.chunk_enrichment_enabled else "none",
            processed_at=processed_at,
            source_file_type=state.get("file_type", ""),
        )


def _append_processing_history(parsed_dir: str, report: dict) -> None:
    history_path = os.path.join(parsed_dir, "processing_history.json")
    try:
        with open(history_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []
    if not isinstance(existing, list):
        existing = []

    summary = quality_summary(report)
    existing.append({
        "processed_at": summary["processed_at"],
        "parser_version": summary["parser_version"],
        "chunker_version": summary["chunker_version"],
        "enrichment_profile": summary["enrichment_profile"],
        "chunk_count": int(report.get("chunk_count") or 0),
        "quality_status": summary["quality_status"],
        "quality_warning_count": summary["quality_warning_count"],
        "source_file_type": str(report.get("source_file_type") or ""),
        "quality_version": str(report.get("quality_version") or ""),
    })
    _write_json_artifact(history_path, existing)


def _write_quality_artifacts(state: IngestionState, config: RunnableConfig, chunks: list[dict]) -> dict:
    report = _build_quality_report(state, config, chunks)
    _write_json_artifact(os.path.join(state["parsed_dir"], "chunk_quality.json"), report)
    _append_processing_history(state["parsed_dir"], report)
    return report


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def entry(state: IngestionState, config: RunnableConfig) -> dict:
    """初始化 parsed_dir 和 entity_name。"""
    document_id = state["document_id"]
    parsed_dir = os.path.abspath(
        os.path.join(settings.GENERAL_PARSED_DIR, document_id)
    )
    _reset_parsed_dir(parsed_dir)
    # 优先级：用户指定 > 文件名提取 > 空字符串
    entity_name = state.get("entity_name") or extract_entity_name(state["filename"])

    updater = _get_updater(config)
    if updater:
        updater(document_id, "processing")

    return {
        "parsed_dir": parsed_dir,
        "entity_name": entity_name,
        "status": "processing",
        "image_count": 0,
        "chunk_count": 0,
    }


def parse_pdf(state: IngestionState, config: RunnableConfig) -> dict:
    """MinerU Online API 解析 PDF。"""
    from app.rag.parsing.mineru_parser import parse_pdf_to_markdown

    updater = _get_updater(config)
    if updater:
        updater(state["document_id"], "parsing")

    result = parse_pdf_to_markdown(state["source_path"], state["parsed_dir"])
    return {
        "markdown": result.markdown_content,
        "image_count": _count_images(result.images_dir),
        "images_dir": result.images_dir,
        "status": "parsing",
    }


def read_markdown_file(state: IngestionState, config: RunnableConfig) -> dict:
    """读取 .md 文件。"""
    from app.rag.parsing.markdown_loader import read_markdown

    updater = _get_updater(config)
    if updater:
        updater(state["document_id"], "reading")

    markdown = read_markdown(state["source_path"])
    return {"markdown": markdown, "status": "reading"}


def parse_md_zip(state: IngestionState, config: RunnableConfig) -> dict:
    """解压 Markdown zip 到标准 parsed_dir 结构。"""
    from app.rag.parsing.mineru_parser import parse_md_zip as _parse_md_zip

    updater = _get_updater(config)
    if updater:
        updater(state["document_id"], "parsing")

    result = _parse_md_zip(state["source_path"], state["parsed_dir"])
    return {
        "markdown": result.markdown_content,
        "image_count": _count_images(result.images_dir),
        "images_dir": result.images_dir,
        "status": "parsing",
    }


def normalize(state: IngestionState, config: RunnableConfig) -> dict:
    """标准化 markdown 并写入 parsed_dir。"""
    from app.rag.parsing.markdown_loader import normalize_markdown, write_markdown

    updater = _get_updater(config)
    if updater:
        updater(state["document_id"], "normalizing")

    normalized = normalize_markdown(state["markdown"])
    write_markdown(os.path.join(state["parsed_dir"], "document.md"), normalized)
    return {"markdown": normalized, "status": "normalizing"}


def describe_images(state: IngestionState, config: RunnableConfig) -> dict:
    """调用 VL 模型生成图片描述（仅 PDF 路径且开关开启时）。"""
    if not settings.IMAGE_DESCRIPTION_ENABLED:
        return {"image_descriptions": {}}

    images_dir = state.get("images_dir")
    if not images_dir or not os.path.isdir(images_dir):
        return {"image_descriptions": {}}

    from app.rag.parsing.image_describer import batch_describe_images

    descriptions = batch_describe_images(images_dir)

    # 将绝对路径转为相对 parsed_dir 的路径，方便 asset 接口服务
    parsed_dir = os.path.normpath(state["parsed_dir"])
    for key, entry in descriptions.items():
        abs_path = entry.get("image_path", "")
        if abs_path and os.path.isabs(abs_path):
            try:
                entry["image_path"] = os.path.relpath(abs_path, parsed_dir).replace(os.sep, "/")
            except ValueError:
                pass  # 不同盘符，保持原样

    return {"image_descriptions": descriptions}


def chunk(state: IngestionState, config: RunnableConfig) -> dict:
    """分块。"""
    from app.rag.chunking.markdown_chunker import split_markdown_document
    from app.rag.ingestion.config import get_ingestion_config

    updater = _get_updater(config)
    if updater:
        updater(state["document_id"], "chunking")

    cfg = get_ingestion_config(config)
    chunks, _table_count = split_markdown_document(
        state["markdown"],
        document_id=state["document_id"],
        filename=state["filename"],
        source_path=state["source_path"],
        parsed_dir=state["parsed_dir"],
        entity_name=state["entity_name"],
        image_descriptions=state.get("image_descriptions"),
        cfg=cfg,
    )
    _write_chunks_artifact(state["parsed_dir"], chunks)
    return {"chunks": chunks, "status": "chunking"}


def enrich_search_metadata(state: IngestionState, config: RunnableConfig) -> dict:
    """Add retrieval-only enrichment fields and persist parsed artifacts."""
    from app.rag.chunking.enrichment import enrich_chunks as _enrich_chunks
    from app.rag.ingestion.config import get_ingestion_config

    chunks = state.get("chunks", [])
    cfg = get_ingestion_config(config)
    if not cfg.chunk_enrichment_enabled or cfg.chunk_enrichment_profile == "none":
        _write_chunks_artifact(state["parsed_dir"], chunks)
        quality_report = _write_quality_artifacts(state, config, chunks)
        return {"chunks": chunks, "quality_report": quality_report}

    updater = _get_updater(config)
    if updater:
        updater(state["document_id"], "enriching")

    enriched = _enrich_chunks(chunks, profile=cfg.chunk_enrichment_profile)
    _write_enrichment_artifacts(state["parsed_dir"], enriched)
    quality_report = _write_quality_artifacts(state, config, enriched)
    return {"chunks": enriched, "quality_report": quality_report, "status": "enriching"}


def _write_enrichment_artifacts(parsed_dir: str, chunks: list[dict]) -> None:
    _write_chunks_artifact(parsed_dir, chunks)

    enrichment = [
        {
            "chunk_key": chunk.get("chunk_key", ""),
            "enrichment_profile": chunk.get("enrichment_profile", ""),
            "keywords": chunk.get("keywords", []),
            "structured_tags": chunk.get("structured_tags", []),
            "search_text": chunk.get("search_text", ""),
        }
        for chunk in chunks
    ]
    artifact_path = os.path.join(parsed_dir, "chunk_enrichment.json")
    _write_json_artifact(artifact_path, enrichment)


def embed_and_save(state: IngestionState, config: RunnableConfig) -> dict:
    """Embedding + Milvus 入库。"""
    from app.rag.embeddings.dense_embedding import embed_chunks
    from app.rag.vectorstores.general_milvus import upsert_document_chunks

    doc_id = state["document_id"]
    updater = _get_updater(config)

    if updater:
        updater(doc_id, "embedding")
    embedded = embed_chunks(state["chunks"])

    if updater:
        updater(doc_id, "saving")
    upsert_document_chunks(doc_id, embedded)

    return {
        "embedded_chunks": embedded,
        "chunk_count": len(embedded),
        "status": "completed",
    }


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def route_by_file_type(state: IngestionState) -> str:
    if state["file_type"] == "pdf":
        return "parse_pdf"
    if state["file_type"] == "md_zip":
        return "parse_md_zip"
    return "read_markdown"


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

_builder = StateGraph(IngestionState)

_builder.add_node("entry", entry)
_builder.add_node("parse_pdf", parse_pdf)
_builder.add_node("parse_md_zip", parse_md_zip)
_builder.add_node("read_markdown", read_markdown_file)
_builder.add_node("describe_images", describe_images)
_builder.add_node("normalize", normalize)
_builder.add_node("chunk", chunk)
_builder.add_node("enrich_search_metadata", enrich_search_metadata)
_builder.add_node("embed_and_save", embed_and_save)

_builder.add_edge(START, "entry")
_builder.add_conditional_edges(
    "entry",
    route_by_file_type,
    {"parse_pdf": "parse_pdf", "parse_md_zip": "parse_md_zip", "read_markdown": "read_markdown"},
)
_builder.add_edge("parse_pdf", "describe_images")
_builder.add_edge("parse_md_zip", "describe_images")
_builder.add_edge("read_markdown", "normalize")
_builder.add_edge("describe_images", "normalize")
_builder.add_edge("normalize", "chunk")
_builder.add_edge("chunk", "enrich_search_metadata")
_builder.add_edge("enrich_search_metadata", "embed_and_save")
_builder.add_edge("embed_and_save", END)

ingestion_graph = _builder.compile()


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def run_ingestion_graph(doc: dict, entity_name: str = "", config: RunnableConfig | None = None) -> dict:
    """入口函数，供 document_service 调用。"""
    result = ingestion_graph.invoke(
        {
            "document_id": doc["document_id"],
            "filename": doc["filename"],
            "file_type": doc["file_type"],
            "source_path": doc["source_path"],
            "entity_name": entity_name,
        },
        config=config,
    )
    return {
        "chunk_count": result.get("chunk_count", 0),
        "image_count": result.get("image_count", 0),
        **quality_summary(result.get("quality_report", {})),
    }
