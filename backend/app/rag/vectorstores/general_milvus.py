"""Milvus collection for general text-only documents."""

import json
import logging

from pymilvus import DataType, Function, FunctionType, MilvusClient

from app.config import settings
from app.rag.query.filter_utils import escape_milvus_string

logger = logging.getLogger(__name__)

COLLECTION_NAME = "general_documents"
client = MilvusClient(uri=settings.MILVUS_URI)
QUERY_TIMEOUT = 30

CHUNK_OUTPUT_FIELDS = [
    "chunk_id",
    "chunk_key",
    "content",
    "keywords",
    "structured_tags",
    "title",
    "parent_title",
    "section_title",
    "part",
    "file_title",
    "source",
    "document_id",
    "page",
    "source_type",
    "table_id",
    "table_title",
    "raw_table_path",
    "image_paths",
    "table_tokens",
    "entity_name",
]

ENRICHMENT_STORAGE_FIELDS = {"search_text", "keywords", "structured_tags"}
SCHEMA_FIELD_NAMES = set(CHUNK_OUTPUT_FIELDS) | ENRICHMENT_STORAGE_FIELDS | {"dense", "sparse"}
OPTIONAL_OUTPUT_FIELDS = {"chunk_key", "search_text", "keywords", "structured_tags"}
_FIELD_NAMES_CACHE: set[str] | None = None


def ensure_collection():
    """Create general_documents collection if it does not exist."""
    global _FIELD_NAMES_CACHE
    if client.has_collection(collection_name=COLLECTION_NAME):
        return

    schema = client.create_schema()
    schema.add_field(field_name="chunk_id", datatype=DataType.INT64, is_primary=True, auto_id=True)
    schema.add_field(field_name="chunk_key", datatype=DataType.VARCHAR, max_length=80, nullable=True)
    schema.add_field(
        field_name="content",
        datatype=DataType.VARCHAR,
        max_length=65535,
        enable_analyzer=True,
        analyzer_params={"tokenizer": "jieba", "filter": ["cnalphanumonly"]},
    )
    schema.add_field(
        field_name="search_text",
        datatype=DataType.VARCHAR,
        max_length=65535,
        enable_analyzer=True,
        analyzer_params={"tokenizer": "jieba", "filter": ["cnalphanumonly"]},
    )
    schema.add_field(field_name="keywords", datatype=DataType.VARCHAR, max_length=8192, nullable=True)
    schema.add_field(field_name="structured_tags", datatype=DataType.VARCHAR, max_length=4096, nullable=True)
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
        name="general_search_text_bm25",
        input_field_names=["search_text"],
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
    _FIELD_NAMES_CACHE = set(SCHEMA_FIELD_NAMES)
    logger.info("创建 collection '%s' 成功 (dim=%d)", COLLECTION_NAME, settings.EMBEDDING_DIM)


def collection_field_names() -> set[str]:
    """Return current collection field names, tolerant of old Milvus SDK shapes."""
    global _FIELD_NAMES_CACHE
    if _FIELD_NAMES_CACHE is not None:
        return _FIELD_NAMES_CACHE
    if not client.has_collection(collection_name=COLLECTION_NAME):
        _FIELD_NAMES_CACHE = set()
        return _FIELD_NAMES_CACHE

    desc = client.describe_collection(collection_name=COLLECTION_NAME)
    if isinstance(desc, dict):
        fields = desc.get("fields")
        if fields is None and isinstance(desc.get("schema"), dict):
            fields = desc["schema"].get("fields")
    else:
        fields = getattr(desc, "fields", None)
        schema = getattr(desc, "schema", None)
        if fields is None and schema is not None:
            fields = getattr(schema, "fields", None)

    names: set[str] = set()
    for field in fields or []:
        if isinstance(field, dict):
            name = field.get("name") or field.get("field_name")
        else:
            name = getattr(field, "name", None) or getattr(field, "field_name", None)
        if name:
            names.add(str(name))

    _FIELD_NAMES_CACHE = names
    return names


def collection_has_field(field_name: str) -> bool:
    try:
        return field_name in collection_field_names()
    except Exception:
        logger.warning("Failed to inspect Milvus collection schema", exc_info=True)
        return False


def available_output_fields(fields: list[str]) -> list[str]:
    """Remove optional fields missing from old collections."""
    try:
        names = collection_field_names()
    except Exception:
        logger.warning("Failed to inspect Milvus collection schema", exc_info=True)
        return [field for field in fields if field not in OPTIONAL_OUTPUT_FIELDS]
    if not names:
        return [field for field in fields if field not in OPTIONAL_OUTPUT_FIELDS]
    return [field for field in fields if field in names or field not in OPTIONAL_OUTPUT_FIELDS]


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


def query_chunks_by_document_id(document_id: str, limit: int = 10000) -> list[dict]:
    """Return stored chunks for one document from Milvus, excluding vector fields."""
    if not client.has_collection(collection_name=COLLECTION_NAME):
        return []

    # document_id is expected to be a hex UUID; Milvus SDK has no parameterized queries
    rows = client.query(
        collection_name=COLLECTION_NAME,
        filter=f'document_id == "{document_id}"',
        output_fields=available_output_fields(CHUNK_OUTPUT_FIELDS),
        limit=limit,
        timeout=QUERY_TIMEOUT,
    )
    return rows or []


def query_chunk_by_key(document_id: str, chunk_key: str) -> dict | None:
    """Return one chunk by stable chunk_key from Milvus, or None on old schema/miss."""
    if not client.has_collection(collection_name=COLLECTION_NAME):
        return None
    if not collection_has_field("chunk_key"):
        return None

    doc = escape_milvus_string(document_id)
    key = escape_milvus_string(chunk_key)
    rows = client.query(
        collection_name=COLLECTION_NAME,
        filter=f'document_id == "{doc}" and chunk_key == "{key}"',
        output_fields=available_output_fields(CHUNK_OUTPUT_FIELDS),
        limit=1,
        timeout=QUERY_TIMEOUT,
    )
    return (rows or [None])[0]


def upsert_document_chunks(document_id: str, chunks: list[dict]):
    """Idempotently write embedded chunks to Milvus."""
    ensure_collection()
    delete_by_document_id(document_id)
    if not chunks:
        return {"insert_count": 0}

    fields = collection_field_names()
    include_chunk_key = "chunk_key" in fields
    include_enrichment = ENRICHMENT_STORAGE_FIELDS.issubset(fields)
    records = [
        _to_milvus_row(
            chunk,
            include_chunk_key=include_chunk_key,
            include_enrichment=include_enrichment,
        )
        for chunk in chunks
    ]
    result = client.insert(collection_name=COLLECTION_NAME, data=records)
    client.flush(collection_name=COLLECTION_NAME)
    return result


def _to_milvus_row(
    chunk: dict,
    *,
    include_chunk_key: bool = True,
    include_enrichment: bool = True,
) -> dict:
    row = {
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
    if include_chunk_key:
        row["chunk_key"] = chunk.get("chunk_key", "")
    if include_enrichment:
        row["search_text"] = chunk.get("search_text") or chunk.get("content", "")
        row["keywords"] = _json_list(chunk.get("keywords"))
        row["structured_tags"] = _json_list(chunk.get("structured_tags"))
    return row


def _json_list(value) -> str:
    if value is None:
        return "[]"
    if isinstance(value, str):
        return value
    return json.dumps(list(value), ensure_ascii=False)
