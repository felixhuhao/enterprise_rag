"""Unit tests for multi-entity routing support."""

from app.rag.query.build_prompt import build_prompt_node
from app.rag.query.config import QueryConfig
from app.rag.query.rewrite_query import rewrite_query_node


def test_rewrite_skips_multi_entity_mode():
    state = {
        "query": "实体A和实体B的流程，其差异是什么？",
        "confirmed_entity": "实体A",
        "entity_mode": "multi_explicit",
    }

    result = rewrite_query_node(state, {"configurable": {"query_config": QueryConfig()}})

    assert result["rewritten_query"] == state["query"]


def test_build_prompt_includes_entity_name_in_context():
    state = {
        "query": "实体A和实体B分别怎么处理审批？",
        "entity_mode": "multi_explicit",
        "search_results": [{
            "document_id": "doc-a",
            "file_title": "审批制度.md",
            "entity_name": "实体A",
            "section_title": "审批流程",
            "source_type": "text",
            "content": "实体A需要直属主管审批。",
            "image_paths": [],
        }],
    }

    result = build_prompt_node(state, {"configurable": {"query_config": QueryConfig()}})

    assert "实体: 实体A" in result["context_text"]
    assert result["context_map"]["C1"]["entity_name"] == "实体A"
