import logging

from pymilvus import MilvusClient, DataType, Function, FunctionType

from app.config import settings

logger = logging.getLogger(__name__)

COLLECTION_NAME = "multimodal_rag"
CONTEXT_COLLECTION_NAME = "t_context_collection"

client = MilvusClient(uri=settings.MILVUS_URI)


def create_collection():
    """创建混合检索 collection（dense 向量 + BM25 稀疏向量）"""

    schema = client.create_schema()

    # 主键
    schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True, auto_id=True)

    # 文本内容：启用 jieba 分词，BM25 自动从此字段生成稀疏向量
    schema.add_field(
        field_name="text", datatype=DataType.VARCHAR, max_length=65535,
        enable_analyzer=True,
        analyzer_params={"tokenizer": "jieba", "filter": ["cnalphanumonly"]},
    )

    # 元数据
    schema.add_field(field_name="source", datatype=DataType.VARCHAR, max_length=512, nullable=True)
    schema.add_field(field_name="title", datatype=DataType.VARCHAR, max_length=1000, nullable=True)
    schema.add_field(field_name="image_paths", datatype=DataType.VARCHAR, max_length=8192, nullable=True)

    # 稠密向量（qwen3-vl-embedding fusion）
    schema.add_field(field_name="dense", datatype=DataType.FLOAT_VECTOR, dim=settings.VL_EMBEDDING_DIM)

    # 稀疏向量（BM25 自动生成）
    schema.add_field(field_name="sparse", datatype=DataType.SPARSE_FLOAT_VECTOR)

    # BM25 函数：text → sparse
    bm25_function = Function(
        name="text_bm25_emb",
        input_field_names=["text"],
        output_field_names=["sparse"],
        function_type=FunctionType.BM25,
    )
    schema.add_function(bm25_function)

    # 索引
    index_params = client.prepare_index_params()

    index_params.add_index(
        field_name="sparse",
        index_name="sparse_inverted_index",
        index_type="SPARSE_INVERTED_INDEX",
        metric_type="BM25",
        params={
            "inverted_index_algo": "DAAT_MAXSCORE",
            "bm25_k1": 1.2,
            "bm25_b": 0.75,
        },
    )

    index_params.add_index(
        field_name="dense",
        index_name="dense_index",
        index_type="AUTOINDEX",
        metric_type="COSINE",
    )

    client.create_collection(
        collection_name=COLLECTION_NAME,
        schema=schema,
        index_params=index_params,
    )
    logger.info("创建 collection '%s' 成功 (dim=%d, hybrid=True)", COLLECTION_NAME, settings.VL_EMBEDDING_DIM)


def drop_collection():
    """删除 collection"""
    client.drop_collection(collection_name=COLLECTION_NAME)
    logger.info("已删除 collection '%s'", COLLECTION_NAME)


if __name__ == "__main__":
    drop_collection()
    create_collection()
    res = client.describe_collection(collection_name=COLLECTION_NAME)
    print(res)


def create_context_collection():
    """创建上下文历史 collection（存储对话记忆，支持 dense + BM25 混合检索）"""

    schema = client.create_schema()

    # 主键
    schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True, auto_id=True)

    # 上下文文本：启用 jieba 分词，BM25 自动生成稀疏向量
    schema.add_field(
        field_name="context_text",
        datatype=DataType.VARCHAR,
        max_length=65535,
        enable_analyzer=True,
        analyzer_params={"tokenizer": "jieba", "filter": ["cnalphanumonly"]},
    )

    # 元数据
    schema.add_field(field_name="user", datatype=DataType.VARCHAR, max_length=256)
    schema.add_field(field_name="timestamp", datatype=DataType.INT64)
    schema.add_field(field_name="message_type", datatype=DataType.VARCHAR, max_length=64)

    # 稠密向量
    schema.add_field(field_name="context_dense", datatype=DataType.FLOAT_VECTOR, dim=settings.EMBEDDING_DIM)

    # 稀疏向量（BM25 自动生成）
    schema.add_field(field_name="context_sparse", datatype=DataType.SPARSE_FLOAT_VECTOR)

    # BM25 函数：context_text → context_sparse
    bm25_function = Function(
        name="context_bm25",
        input_field_names=["context_text"],
        output_field_names=["context_sparse"],
        function_type=FunctionType.BM25,
    )
    schema.add_function(bm25_function)

    # 索引
    index_params = client.prepare_index_params()

    index_params.add_index(
        field_name="context_sparse",
        index_name="context_sparse_index",
        index_type="SPARSE_INVERTED_INDEX",
        metric_type="BM25",
        params={
            "inverted_index_algo": "DAAT_MAXSCORE",
            "bm25_k1": 1.2,
            "bm25_b": 0.75,
        },
    )

    index_params.add_index(
        field_name="context_dense",
        index_name="context_dense_index",
        index_type="AUTOINDEX",
        metric_type="IP",
    )

    client.create_collection(
        collection_name=CONTEXT_COLLECTION_NAME,
        schema=schema,
        index_params=index_params,
    )
    logger.info("创建上下文 collection '%s' 成功 (dim=%d, hybrid=True)", CONTEXT_COLLECTION_NAME, settings.EMBEDDING_DIM)
