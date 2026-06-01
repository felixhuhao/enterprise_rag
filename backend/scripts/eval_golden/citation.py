"""Citation scoring and retrieval-hit metrics."""

def score_citation(citations: list, expected_documents: list,
                   min_expected_citations: int = 1, item: dict = None) -> dict:
    """Score citation recall against expected documents.

    Extended with section matching and anchor text tracking.
    - citation_doc_score: document-level match (existing logic)
    - section_hit: whether expected_sections appear in citation section_titles
    - anchor_hit: null (requires chunk content not available in citation)
    """
    try:
        min_expected_citations = int(min_expected_citations)
    except (TypeError, ValueError):
        min_expected_citations = 1
    min_expected_citations = max(1, min_expected_citations)

    if not expected_documents:
        result = {"citation_score": 1.0, "doc_hits": 0, "matched_docs": []}
    else:
        cited_files = set()
        for c in citations:
            ft = c.get("file_title", "") or c.get("source", "") or ""
            cited_files.add(ft)

        matched = []
        for ed in expected_documents:
            for cf in cited_files:
                if ed in cf or cf in ed:
                    matched.append(ed)
                    break

        score = min(len(matched) / min_expected_citations, 1.0)
        result = {
            "citation_score": round(score, 4),
            "citation_doc_score": round(score, 4),
            "doc_hits": len(matched),
            "matched_docs": matched,
        }

    # Section matching (from citation section_title)
    if item and item.get("expected_sections"):
        expected_sections = item["expected_sections"]
        cited_sections = {c.get("section_title", "") for c in citations}
        section_matched = []
        section_missed = []
        for es in expected_sections:
            if any(es in cs for cs in cited_sections):
                section_matched.append(es)
            else:
                section_missed.append(es)
        result["section_hit"] = len(section_matched) > 0
        result["section_matched"] = section_matched
        result["section_missed"] = section_missed

    # Anchor text — not available in citation metadata, record as skipped
    if item and item.get("expected_anchor_text"):
        result["anchor_hit"] = None  # requires chunk content, not available
        result["anchor_matched"] = []
        result["anchor_missed"] = item["expected_anchor_text"]

    return result


def _citation_output_fields(cite: dict) -> dict:
    """Normalize citation scoring details for result rows."""
    return {
        "citation_doc_score": cite.get("citation_doc_score", cite.get("citation_score")),
        "citation_section_hit": cite.get("section_hit"),
        "citation_section_matched": cite.get("section_matched", []),
        "citation_section_missed": cite.get("section_missed", []),
        "citation_anchor_hit": cite.get("anchor_hit"),
        "citation_anchor_matched": cite.get("anchor_matched", []),
        "citation_anchor_missed": cite.get("anchor_missed", []),
    }


# ---------------------------------------------------------------------------
# Hit@K from rerank results
# ---------------------------------------------------------------------------


def compute_hit_at_k(rerank_results: list[dict], expected_documents: list[str],
                     k: int = 5) -> bool:
    """Check if any expected_document appears in top-k reranked results."""
    if not expected_documents or not rerank_results:
        return False
    top_k = rerank_results[:k]
    top_k_docs = {r.get("file_title", "") or r.get("source", "") for r in top_k}
    for ed in expected_documents:
        if any(ed in doc or doc in ed for doc in top_k_docs):
            return True
    return False


def compute_chunk_hit_at_k(rerank_results: list[dict], expected_chunk_keys: list[str],
                           k: int = 5) -> bool:
    """Check if any expected chunk key appears in top-k reranked/retrieved results."""
    if not expected_chunk_keys or not rerank_results:
        return False
    expected = {str(key) for key in expected_chunk_keys if key}
    top_k_keys = {str(r.get("chunk_key", "")) for r in rerank_results[:k]}
    return bool(expected & top_k_keys)


def is_hit_metric_applicable(item: dict) -> bool:
    """Hit@K applies only to answerable cases with explicit expected docs."""
    return bool(_expected_documents(item) or _expected_chunk_keys(item)) and _expected_behavior(item) == "answer"


def _expected_documents(item: dict) -> list[str]:
    docs = item.get("expected_docs", item.get("expected_documents", []))
    return docs if isinstance(docs, list) else []


def _expected_chunk_keys(item: dict) -> list[str]:
    keys = item.get("expected_chunk_keys", [])
    return keys if isinstance(keys, list) else []


def _case_slices(item: dict) -> list[str]:
    slices = item.get("slices", item.get("tags", []))
    return slices if isinstance(slices, list) else []


def _expected_behavior(item: dict) -> str:
    behavior = str(item.get("expected_behavior", "")).strip().lower()
    if behavior in {"answer", "no_answer"}:
        return behavior
    return "answer" if item.get("should_answer", True) else "no_answer"


def _apply_hit_metrics(row: dict, results: list[dict], item: dict) -> None:
    expected_docs = _expected_documents(item)
    expected_chunk_keys = _expected_chunk_keys(item)
    hit_applicable = is_hit_metric_applicable(item)
    row["hit_metric_applicable"] = hit_applicable
    row["doc_hit_at_5"] = compute_hit_at_k(results, expected_docs, k=5) if expected_docs else None
    row["doc_hit_at_10"] = compute_hit_at_k(results, expected_docs, k=10) if expected_docs else None
    row["chunk_hit_at_5"] = compute_chunk_hit_at_k(results, expected_chunk_keys, k=5) if expected_chunk_keys else None
    row["chunk_hit_at_10"] = compute_chunk_hit_at_k(results, expected_chunk_keys, k=10) if expected_chunk_keys else None
    row["hit_at_5"] = (
        bool(row.get("doc_hit_at_5")) or bool(row.get("chunk_hit_at_5"))
    ) if hit_applicable else None
    row["hit_at_10"] = (
        bool(row.get("doc_hit_at_10")) or bool(row.get("chunk_hit_at_10"))
    ) if hit_applicable else None
