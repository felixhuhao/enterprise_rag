"""Validate citations: extract [C1]/[C2] from answer, match against context_map."""

from __future__ import annotations

import re

from app.rag.query.state import QueryState


_CITATION_RE = re.compile(r"[\[【（(]\s*C\s*(\d+)\s*[\]】）)]", re.IGNORECASE)


def validate_citations_node(state: QueryState) -> dict:
    """从 LLM 回答中提取引用，校验是否来自 context_map，过滤幻觉引用。"""
    answer = state.get("answer", "")
    context_map = state.get("context_map", {})

    found = set(_CITATION_RE.findall(answer))

    valid_citations = []
    for cid_str in sorted(found, key=int):
        cid = f"C{cid_str}"
        if cid in context_map:
            citation = {"id": cid}
            citation.update(context_map[cid])
            valid_citations.append(citation)

    return {"citations": valid_citations}
