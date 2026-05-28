"""LangGraph query workflow.

START → entity_confirm → rewrite_query → [search, hyde_search] → rrf_fusion
→ table_expand → rerank → build_prompt → generate_answer → validate_citations → END
"""

from langgraph.constants import END, START
from langgraph.graph import StateGraph

from app.rag.query.build_prompt import build_prompt_node
from app.rag.query.config import QueryConfig, get_default_query_config
from app.rag.query.entity_confirm import entity_confirm_node
from app.rag.query.generate import generate_answer_node
from app.rag.query.hyde_search import hyde_search_node
from app.rag.query.rerank import rerank_node
from app.rag.query.rewrite_query import rewrite_query_node
from app.rag.query.rrf_fusion import rrf_fusion_node
from app.rag.query.search import search_node
from app.rag.query.state import QueryState
from app.rag.query.table_expand import table_expand_node
from app.rag.query.validate_citations import validate_citations_node

_builder = StateGraph(QueryState)

_builder.add_node("entity_confirm", entity_confirm_node)
_builder.add_node("rewrite_query", rewrite_query_node)
_builder.add_node("search", search_node)
_builder.add_node("hyde_search", hyde_search_node)
_builder.add_node("rrf_fusion", rrf_fusion_node)
_builder.add_node("table_expand", table_expand_node)
_builder.add_node("rerank", rerank_node)
_builder.add_node("build_prompt", build_prompt_node)
_builder.add_node("generate_answer", generate_answer_node)
_builder.add_node("validate_citations", validate_citations_node)

_builder.add_edge(START, "entity_confirm")
_builder.add_edge("entity_confirm", "rewrite_query")
# fan-out: rewrite_query → search + hyde_search 并行
_builder.add_edge("rewrite_query", "search")
_builder.add_edge("rewrite_query", "hyde_search")
# fan-in: 两路汇聚到 rrf_fusion
_builder.add_edge("search", "rrf_fusion")
_builder.add_edge("hyde_search", "rrf_fusion")
_builder.add_edge("rrf_fusion", "table_expand")
_builder.add_edge("table_expand", "rerank")
_builder.add_edge("rerank", "build_prompt")
_builder.add_edge("build_prompt", "generate_answer")
_builder.add_edge("generate_answer", "validate_citations")
_builder.add_edge("validate_citations", END)

query_graph = _builder.compile()


def run_query_graph(query: str, query_config: QueryConfig | None = None) -> dict:
    """入口函数。"""
    config = {"configurable": {"query_config": query_config or get_default_query_config()}}
    result = query_graph.invoke({"query": query}, config=config)
    return {
        "answer": result.get("answer", ""),
        "citations": result.get("citations", []),
        "results_count": len(result.get("search_results", [])),
        "entity": result.get("confirmed_entity", ""),
        "rewritten_query": result.get("rewritten_query", ""),
        "entity_mode": result.get("entity_mode", "none"),
        "matched_entities": result.get("matched_entities", []),
        "per_entity_counts": result.get("per_entity_counts", {}),
    }
