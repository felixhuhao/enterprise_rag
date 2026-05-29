"""Unit tests for search budget consumption."""

import sys
import types
from unittest.mock import patch

from app.rag.query.config import QueryConfig

pymilvus_stub = types.ModuleType("pymilvus")
pymilvus_stub.AnnSearchRequest = object
pymilvus_stub.WeightedRanker = object
sys.modules.setdefault("pymilvus", pymilvus_stub)

general_milvus_stub = types.ModuleType("app.rag.vectorstores.general_milvus")
general_milvus_stub.COLLECTION_NAME = "test_collection"
general_milvus_stub.client = object()
sys.modules.setdefault("app.rag.vectorstores.general_milvus", general_milvus_stub)

from app.rag.query.search import _multi_entity_search


def test_multi_entity_uses_per_entity_min_k():
    state = {
        "query": "A B C 的制度？",
        "matched_entities": ["A", "B", "C"],
        "query_plan": {
            "budget": {
                "search_limit": 10,
                "per_entity_min_k": 8,
            },
        },
    }
    config = {"configurable": {"query_config": QueryConfig()}}

    def fake_hybrid(query_dense, query_text, entity_filter, limit, cfg):
        return [{"chunk_id": entity_filter, "document_id": entity_filter, "score": 0.9}]

    with (
        patch("app.rag.query.search.dense_embedding.embed_query", return_value=[0.1, 0.2]),
        patch("app.rag.query.search._hybrid_search_limited", side_effect=fake_hybrid) as hybrid,
        patch("app.rag.query.search._dense_only_search_limited") as dense_only,
    ):
        out = _multi_entity_search(state, config, state["query"], QueryConfig())

    assert [call.args[3] for call in hybrid.call_args_list] == [8, 8, 8]
    assert dense_only.call_count == 0
    assert out["per_entity_counts"] == {"A": 1, "B": 1, "C": 1}
    assert len(out["search_results"]) == 3
