"""Final context diversification after rerank.

Recall/discovery queries need coverage across documents more than repeated
near-duplicate chunks from the same section.
"""

from __future__ import annotations

from langgraph.graph.state import RunnableConfig

from app.rag.query.config import get_query_config
from app.rag.query.planner import get_query_plan, plan_budget
from app.rag.query.state import QueryState


_DIVERSIFY_FLAVORS = {"recall", "discovery"}
_MIN_DIVERSE_SCORE = 0.5


def diversify_context_node(state: QueryState, config: RunnableConfig) -> dict:
    cfg = get_query_config(config)
    plan = get_query_plan(state, config)
    flavor = plan.get("retrieval_flavor", cfg.retrieval_flavor)
    ranked_results = state.get("search_results", [])
    candidates = state.get("rerank_candidates") or ranked_results
    if flavor in _DIVERSIFY_FLAVORS:
        budget = plan_budget(state, config)
        target_k = int(budget.get("final_context_k") or cfg.rerank_max_top_k)
    else:
        budget = plan_budget(state, config)
        target_k = len(ranked_results) or int(budget.get("final_context_k") or cfg.rerank_max_top_k)

    if not candidates or target_k <= 0:
        return {
            "search_results": [],
            "rerank_debug": [],
            "context_diversify_debug": _diversify_debug([], [], [], flavor),
        }

    target_k = max(1, target_k)
    deduped = _dedupe_chunks(candidates)
    if flavor in _DIVERSIFY_FLAVORS:
        deduped = _filter_low_confidence(deduped)
        selected = _select_diverse(deduped, target_k)
    else:
        selected = deduped[:target_k]

    return {
        "search_results": selected,
        "rerank_debug": _rerank_debug(selected),
        "context_diversify_debug": _diversify_debug(candidates, deduped, selected, flavor),
    }


def _dedupe_chunks(results: list[dict]) -> list[dict]:
    seen: set[str] = set()
    deduped: list[dict] = []
    for doc in results:
        key = _chunk_key(doc)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(doc)
    return deduped


def _select_diverse(results: list[dict], target_k: int) -> list[dict]:
    selected: list[dict] = []
    selected_keys: set[str] = set()
    selected_sections: set[str] = set()

    for max_per_doc, allow_same_section in ((1, False), (2, False), (target_k, True)):
        doc_counts: dict[str, int] = {}
        for doc in selected:
            doc_counts[_doc_key(doc)] = doc_counts.get(_doc_key(doc), 0) + 1

        for doc in results:
            if len(selected) >= target_k:
                return selected
            key = _chunk_key(doc)
            if key in selected_keys:
                continue
            doc_key = _doc_key(doc)
            if doc_counts.get(doc_key, 0) >= max_per_doc:
                continue
            section_key = _section_key(doc)
            if not allow_same_section and section_key in selected_sections:
                continue
            selected.append(doc)
            selected_keys.add(key)
            selected_sections.add(section_key)
            doc_counts[doc_key] = doc_counts.get(doc_key, 0) + 1

    return selected


def _filter_low_confidence(results: list[dict]) -> list[dict]:
    filtered = [doc for doc in results if _score(doc) >= _MIN_DIVERSE_SCORE]
    return filtered or results


def _score(doc: dict) -> float:
    rerank = doc.get("rerank") or {}
    try:
        return float(rerank.get("final_score", doc.get("score", 0)) or 0)
    except (TypeError, ValueError):
        return 0.0


def _chunk_key(doc: dict) -> str:
    return (
        str(doc.get("chunk_key") or "")
        or str(doc.get("chunk_id") or "")
        or "|".join([
            str(doc.get("document_id") or ""),
            str(doc.get("section_title") or ""),
            str(doc.get("part") or ""),
            str(doc.get("content") or "")[:120],
        ])
    )


def _doc_key(doc: dict) -> str:
    return str(doc.get("document_id") or doc.get("file_title") or "")


def _section_key(doc: dict) -> str:
    return "|".join([_doc_key(doc), str(doc.get("section_title") or "")])


def _rerank_debug(results: list[dict]) -> list[dict]:
    return [
        {
            "index": i + 1,
            "file_title": doc.get("file_title", ""),
            "section_title": doc.get("section_title", ""),
            "source_type": doc.get("source_type", ""),
            **doc.get("rerank", {}),
        }
        for i, doc in enumerate(results[:10])
    ]


def _diversify_debug(candidates: list[dict], deduped: list[dict], selected: list[dict], flavor: str) -> dict:
    return {
        "flavor": flavor,
        "candidate_count": len(candidates),
        "deduped_count": len(deduped),
        "selected_count": len(selected),
        "selected_documents": [doc.get("file_title", "") for doc in selected],
    }
