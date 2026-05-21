"""Milvus collection for general text-only documents."""

import json
import logging

from pymilvus import DataType, Function, FunctionType, MilvusClient

from app.config import settings

logger = logging.getLogger(__name__)

COLLECTION_NAME = "general_documents"
client = MilvusClient(uri=settings.MILVUS_URI)


def ensure_collection():
    """Create general_documents collection if it does not exist."""
    if client.has_collection(collection_name=COLLECTION_NAME):
        return

    schema = client.create_schema()
    schema.add_field(field_name="chunk_id", datatype=DataType.INT64, is_primary=True, auto_id=True)
    schema.add_field(
        field_name="content",
        datatype=DataType.VARCHAR,
        max_length=65535,
        enable_analyzer=True,
        analyzer_params={"tokenizer": "jieba", "filter": ["cnalphanumonly"]},
    )
    schema.add_field(field_name="title", datatype=DataType.VARCHAR, max_length=65535, nullable=True)
    schema.add_field(field_name="parent_title", datatype=DataType.VARCHAR, max_length=65535, nullable=True)
    schema.add_field(field_name="section_title", datatype=DataType.VARCHAR, max_length=65535, nullable=True)
    schema.add_field(field_name="part", datatype=DataType.INT8, nullable=True)
    schema.add_field(field_name="file_title", datatype=DataType.VARCHAR, max_length=65535, nullable=True)
    schema.add_field(field_name="source", datatype=DataType.VARCHAR, max_length=2048, nullable=True)
    schema.add_field(field_name="document_id", datatype=DataType.VARCHAR, max_length=128)
    schema.add_field(field_name="page", datatype=DataType.INT64, nullable=True)
    schema.add_field(field_name="source_type", datatype=DataType.VARCHAR, max_length=64, nullable=True)
    schema.add_field(field_name="table_id", datatype=DataType.VARCHAR, max_length=128, nullable=True)
    schema.add_field(field_name="table_title", datatype=DataType.VARCHAR, max_length=65535, nullable=True)
    schema.add_field(field_name="raw_table_path", datatype=DataType.VARCHAR, max_length=2048, nullable=True)
    schema.add_field(field_name="image_paths", datatype=DataType.VARCHAR, max_length=8192, nullable=True)
    schema.add_field(field_name="table_tokens", datatype=DataType.INT64, nullable=True)
    schema.add_field(field_name="entity_name", datatype=DataType.VARCHAR, max_length=512, nullable=True)
    schema.add_field(field_name="dense", datatype=DataType.FLOAT_VECTOR, dim=settings.EMBEDDING_DIM)
    schema.add_field(field_name="sparse", datatype=DataType.SPARSE_FLOAT_VECTOR)

    bm25_function = Function(
        name="general_content_bm25",
        input_field_names=["content"],
        output_field_names=["sparse"],
        function_type=FunctionType.BM25,
    )
    schema.add_function(bm25_function)

    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="sparse",
        index_name="general_sparse_index",
        index_type="SPARSE_INVERTED_INDEX",
        metric_type="BM25",
        params={
            "inverted_index_algo": "DAAT_MAXSCORE",
            "bm25_k1": 1.2,
            "bm25_b": 0.75,
        },
    )
    index_params.add_index(
        field_name="entity_name",
        index_name="general_entity_index",
        index_type="INVERTED",
    )
    index_params.add_index(
        field_name="dense",
        index_name="general_dense_index",
        index_type="AUTOINDEX",
        metric_type="COSINE",
    )

    client.create_collection(
        collection_name=COLLECTION_NAME,
        schema=schema,
        index_params=index_params,
    )
    logger.info("创建 collection '%s' 成功 (dim=%d)", COLLECTION_NAME, settings.EMBEDDING_DIM)


def delete_by_document_id(document_id: str):
    """Delete existing chunks for one document_id."""
    if not client.has_collection(collection_name=COLLECTION_NAME):
        return
    res = client.delete(
        collection_name=COLLECTION_NAME,
        filter=f'document_id == "{document_id}"',
    )
    client.flush(collection_name=COLLECTION_NAME)
    return res


def upsert_document_chunks(document_id: str, chunks: list[dict]):
    """Idempotently write embedded chunks to Milvus."""
    ensure_collection()
    delete_by_document_id(document_id)
    if not chunks:
        return {"insert_count": 0}

    records = [_to_milvus_row(chunk) for chunk in chunks]
    result = client.insert(collection_name=COLLECTION_NAME, data=records)
    client.flush(collection_name=COLLECTION_NAME)
    return result


def _to_milvus_row(chunk: dict) -> dict:
    return {
        "content": chunk.get("content", ""),
        "title": chunk.get("title", ""),
        "parent_title": chunk.get("parent_title", ""),
        "section_title": chunk.get("section_title", ""),
        "part": int(chunk.get("part") or 0),
        "file_title": chunk.get("file_title", ""),
        "source": chunk.get("source", ""),
        "document_id": chunk.get("document_id", ""),
        "page": chunk.get("page"),
        "source_type": chunk.get("source_type", "text"),
        "table_id": chunk.get("table_id", ""),
        "table_title": chunk.get("table_title", ""),
        "raw_table_path": chunk.get("raw_table_path", ""),
        "image_paths": json.dumps(chunk.get("image_paths", []), ensure_ascii=False),
        "table_tokens": chunk.get("table_tokens"),
        "entity_name": chunk.get("entity_name"),
        "dense": chunk["dense"],
    }
