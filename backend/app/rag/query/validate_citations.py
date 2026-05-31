"""Validate citations: extract [C1]/[C2] from answer, match against context_map."""

from __future__ import annotations

import re

from app.rag.query.state import QueryState


_CITATION_BLOCK_RE = re.compile(r"[\[【（(]([^\]】）)]*C\s*\d+[^\]】）)]*)[\]】）)]", re.IGNORECASE)
_CITATION_ID_RE = re.compile(r"C\s*(\d+)", re.IGNORECASE)


def _extract_citation_numbers(answer: str) -> set[str]:
    found: set[str] = set()
    for block in _CITATION_BLOCK_RE.findall(answer or ""):
        found.update(_CITATION_ID_RE.findall(block))
    return found


def validate_citations_node(state: QueryState) -> dict:
    """Extract inline citations and keep only IDs present in context_map."""
    answer = state.get("answer", "")
    context_map = state.get("context_map", {})

    found = _extract_citation_numbers(answer)

    valid_citations = []
    for cid_str in sorted(found, key=int):
        cid = f"C{cid_str}"
        if cid in context_map:
            citation = {"id": cid}
            citation.update(context_map[cid])
            valid_citations.append(citation)

    if not valid_citations and _should_fallback_to_context_citations(state):
        valid_citations = _fallback_context_citations(context_map)

    return {"citations": valid_citations}


def _should_fallback_to_context_citations(state: QueryState) -> bool:
    """Discovery answers sometimes omit inline [C#]; still expose supporting sources."""
    plan = state.get("query_plan") or {}
    return (
        plan.get("retrieval_flavor") == "discovery"
        or state.get("hop_plan") == "discovery"
        or state.get("entity_mode") == "multi_hop"
    )


def _fallback_context_citations(context_map: dict[str, dict], limit: int = 5) -> list[dict]:
    citations = []
    for cid, meta in list(context_map.items())[:limit]:
        citation = {"id": cid}
        citation.update(meta)
        citations.append(citation)
    return citations
