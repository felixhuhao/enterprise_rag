"""验证 Milvus BM25 查询写法。

测试 AnnSearchRequest 传 text string 给 sparse 字段能否返回结果。
如果失败，退回纯 dense search。
"""

from pymilvus import AnnSearchRequest, WeightedRanker, MilvusClient
from app.config import settings
from app.rag.vectorstores.general_milvus import COLLECTION_NAME

client = MilvusClient(uri=settings.MILVUS_URI)

# 检查 collection 是否存在
if not client.has_collection(COLLECTION_NAME):
    print(f"Collection '{COLLECTION_NAME}' 不存在")
    exit(1)

print(f"Collection '{COLLECTION_NAME}' 存在，开始测试...\n")

OUTPUT_FIELDS = [
    "content", "title", "section_title", "source_type",
    "table_id", "table_tokens", "raw_table_path",
    "document_id", "file_title", "entity_name",
]

QUERY_TEXT = "毛利率"

# ---- Test 1: 纯 dense search（基线） ----
print("=" * 50)
print("Test 1: 纯 dense search（基线）")
print("=" * 50)

from app.rag.embeddings.text_embedding_v4 import _text_embedding

query_dense = _text_embedding.embed_query(QUERY_TEXT)
print(f"Embedding dim: {len(query_dense)}")

results_dense = client.search(
    collection_name=COLLECTION_NAME,
    data=[query_dense],
    anns_field="dense",
    search_params={"metric_type": "COSINE"},
    limit=5,
    output_fields=OUTPUT_FIELDS,
)
print(f"Results count: {len(results_dense[0])}")
for i, hit in enumerate(results_dense[0]):
    print(f"  [{i}] score={hit['distance']:.4f} type={hit['entity'].get('source_type')} "
          f"entity={hit['entity'].get('entity_name', '')} "
          f"file={hit['entity'].get('file_title', '')[:30]}")
    print(f"       content: {hit['entity'].get('content', '')[:80]}...")

print()

# ---- Test 2: 纯 BM25 search（text string） ----
print("=" * 50)
print("Test 2: 纯 BM25 search — AnnSearchRequest(data=[text])")
print("=" * 50)

try:
    sparse_req = AnnSearchRequest(
        data=[QUERY_TEXT],
        anns_field="sparse",
        param={"metric_type": "BM25"},
        limit=5,
    )
    results_bm25 = client.search(
        collection_name=COLLECTION_NAME,
        data=[QUERY_TEXT],
        anns_field="sparse",
        search_params={"metric_type": "BM25"},
        limit=5,
        output_fields=OUTPUT_FIELDS,
    )
    print(f"Results count: {len(results_bm25[0])}")
    for i, hit in enumerate(results_bm25[0]):
        print(f"  [{i}] score={hit['distance']:.4f} type={hit['entity'].get('source_type')} "
              f"entity={hit['entity'].get('entity_name', '')} "
              f"file={hit['entity'].get('file_title', '')[:30]}")
        print(f"       content: {hit['entity'].get('content', '')[:80]}...")
    print("\nBM25 search OK!")
except Exception as e:
    print(f"BM25 search FAILED: {type(e).__name__}: {e}")

print()

# ---- Test 3: Hybrid search (dense + BM25) ----
print("=" * 50)
print("Test 3: Hybrid search — WeightedRanker(0.8, 0.2)")
print("=" * 50)

try:
    dense_req = AnnSearchRequest(
        data=[query_dense],
        anns_field="dense",
        param={"metric_type": "COSINE"},
        limit=5,
        expr=None,
    )
    sparse_req = AnnSearchRequest(
        data=[QUERY_TEXT],
        anns_field="sparse",
        param={"metric_type": "BM25"},
        limit=5,
        expr=None,
    )
    results_hybrid = client.hybrid_search(
        collection_name=COLLECTION_NAME,
        reqs=[dense_req, sparse_req],
        ranker=WeightedRanker(0.8, 0.2),
        limit=5,
        output_fields=OUTPUT_FIELDS,
    )
    print(f"Results count: {len(results_hybrid[0])}")
    for i, hit in enumerate(results_hybrid[0]):
        print(f"  [{i}] score={hit['distance']:.4f} type={hit['entity'].get('source_type')} "
              f"entity={hit['entity'].get('entity_name', '')} "
              f"file={hit['entity'].get('file_title', '')[:30]}")
        print(f"       content: {hit['entity'].get('content', '')[:80]}...")
    print("\nHybrid search OK!")
except Exception as e:
    print(f"Hybrid search FAILED: {type(e).__name__}: {e}")

print()
print("Done.")
