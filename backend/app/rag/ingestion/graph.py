"""LangGraph-based ingestion workflow.

Deterministic state machine: entry → route → parse/read → normalize → chunk → embed_and_save.
No checkpointing, no agent loops.
"""

from __future__ import annotations

import os
import shutil
from typing import Callable, TypedDict

from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.graph.state import RunnableConfig

from app.config import settings
from app.rag.ingestion.service import extract_entity_name


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
    return {"chunks": chunks, "status": "chunking"}


def embed_and_save(state: IngestionState, config: RunnableConfig) -> dict:
    """Embedding + Milvus 入库。"""
    from app.rag.embeddings.text_embedding_v4 import embed_chunks
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
_builder.add_edge("chunk", "embed_and_save")
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
    }
