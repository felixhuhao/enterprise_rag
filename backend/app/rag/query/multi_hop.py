"""Constrained multi-hop retrieval — broad entity discovery + per-entity hop2.

P1 scope: only broad discovery queries (e.g. "哪些公司提到了X").
Seed relational queries ("某公司的竞争对手") → P2.
"""

from __future__ import annotations

import logging
import re
import time

from app.rag.query.config import QueryConfig
from app.rag.query.fallback import empty_fallback_info, merge_fallback_info

logger = logging.getLogger(__name__)

DISCOVERY_KEYWORDS = [
    "哪些公司", "哪些企业", "什么公司",
    "竞争对手", "竞争企业", "竞品",
    "供应商", "客户", "合作伙伴",
    "各自", "分别",
]

RESPONSIBILITY_HOP_KEYWORDS = [
    "谁负责", "由谁负责", "负责人", "这个人", "此人", "还负责", "负责什么",
]


def _decide_multi_hop(entity_mode: str, query: str) -> bool:
    """Rule-based planner: P1 only supports broad/none entity discovery."""
    if entity_mode not in ("broad", "none"):
        return False
    return any(kw in query for kw in DISCOVERY_KEYWORDS + RESPONSIBILITY_HOP_KEYWORDS)


def _discover_entities(
    results: list[dict], seed_entities: set[str], max_n: int,
) -> list[str]:
    """Extract distinct entity_names from hop1 results, excluding seeds."""
    seen = set()
    discovered = []
    for r in results:
        entity = (r.get("entity_name") or "").strip()
        if not entity or entity in seed_entities or entity in seen:
            continue
        seen.add(entity)
        discovered.append(entity)
        if len(discovered) >= max_n:
            break
    return discovered


def _merge_results(
    hop1: list[dict], hop2: list[dict], limit: int,
) -> list[dict]:
    """Merge hop1 + hop2 results, deduplicate by stable chunk_key/chunk_id, sort by score desc."""
    seen: set[int | str] = set()
    merged = []
    for r in sorted(hop1 + hop2, key=lambda r: r.get("score", 0), reverse=True):
        cid = r.get("chunk_key") or r.get("chunk_id")
        if cid is None:
            cid = r.get("content", "")[:40]
        if cid in seen:
            continue
        seen.add(cid)
        merged.append(r)
        if len(merged) >= limit:
            break
    return merged


def _is_responsibility_hop(query: str) -> bool:
    return any(kw in query for kw in RESPONSIBILITY_HOP_KEYWORDS)


def _extract_responsible_people(results: list[dict], max_n: int = 3) -> list[str]:
    """Extract person names from hop1 snippets for responsibility follow-up queries."""
    people: list[str] = []
    for row in results:
        text = f"{row.get('section_title', '')}\n{row.get('content', '')}"
        for pattern in (
            r"(?:由|，|。|\s|^)([\u4e00-\u9fff]{2,3})负责",
            r"\|\s*\d+\s*\|\s*[^|\n]*\|\s*([\u4e00-\u9fff]{2,3})\s*\|",
        ):
            for match in re.finditer(pattern, text):
                person = match.group(1).strip()
                if person in people or person in {"负责人"} or person.endswith(("部门", "小组")):
                    continue
                people.append(person)
                if len(people) >= max_n:
                    return people
    return people


def run_multi_hop_search(
    state: dict, query: str, run_config, cfg: QueryConfig, trace: dict,
) -> dict:
    """Broad entity discovery + per-entity hop2. Returns state update dict."""
    from app.rag.query.filter_utils import build_acl_expr, get_allowed_ids
    from app.rag.query.search import _single_search, search_node

    seed_entities = list(state.get("matched_entities", []))
    seed_entity_set = set(seed_entities)
    hop_trace: list[dict] = []

    t = time.monotonic()

    # ACL filter
    allowed = get_allowed_ids(run_config)
    if allowed is not None and not allowed:
        return {
            "search_results": [], "search_mode": "acl_empty", "search_mode_hyde": "",
            "entity_mode": state.get("entity_mode", "none"),
            "matched_entities": seed_entities, "per_entity_counts": {},
            "hop_plan": "discovery", "hop_trace": [],
            "fallback_info": empty_fallback_info(),
        }
    acl_filter = build_acl_expr(allowed) if allowed else None

    # ── Hop 1: broad search, no entity_filter, with ACL ──
    hop1_result = _single_search(query, None, cfg, acl_filter=acl_filter)
    hop1_results = hop1_result.get("search_results", [])
    hop_trace.append({
        "hop": 1,
        "query": query,
        "entity_filter": "",
        "result_count": len(hop1_results),
        "status": "ok",
    })

    # ── Entity Discover ──
    discovered = _discover_entities(
        hop1_results, seed_entity_set, cfg.multi_hop_max_discovered,
    )
    per_entity_counts: dict[str, int] = {}
    hop2_results: list[dict] = []
    person_results: list[dict] = []
    hop2_status = "no_entities_found"
    person_status = "not_applicable"

    if discovered:
        hop2_state = {
            **state,
            "query": query,
            "rewritten_query": query,
            "entity_mode": "multi_explicit",
            "matched_entities": discovered,
        }
        try:
            hop2_result = search_node(hop2_state, run_config)
            hop2_results = hop2_result.get("search_results", [])
            per_entity_counts = hop2_result.get("per_entity_counts", {})
            fallback_info = merge_fallback_info(
                empty_fallback_info(),
                hop2_result.get("fallback_info"),
            )
            hop2_status = "ok" if hop2_results else "no_results"
        except Exception:
            logger.warning("Hop2 search failed", exc_info=True)
            hop2_results = []
            per_entity_counts = {}
            fallback_info = empty_fallback_info()
            hop2_status = "hop2_failed"
    else:
        fallback_info = empty_fallback_info()

    people = _extract_responsible_people(hop1_results) if _is_responsibility_hop(query) else []
    if people:
        person_status = "ok"
        for person in people:
            try:
                person_query = f"{person} 负责 待办事项 工作 截止日期"
                result = _single_search(person_query, None, cfg, acl_filter=acl_filter)
                person_results.extend(result.get("search_results", []))
                fallback_info = merge_fallback_info(fallback_info, result.get("fallback_info"))
            except Exception:
                logger.warning("Responsibility hop search failed for person=%s", person, exc_info=True)
                person_status = "partial_failed"
    elif _is_responsibility_hop(query):
        person_status = "no_people_found"

    merged = _merge_results(hop1_results, hop2_results + person_results, limit=30)

    hop_trace.append({
        "hop": 2,
        "discovered_entities": discovered,
        "per_entity_counts": per_entity_counts,
        "result_count": len(hop2_results),
        "status": hop2_status,
    })
    if _is_responsibility_hop(query):
        hop_trace.append({
            "hop": 3,
            "type": "responsibility_followup",
            "people": people,
            "result_count": len(person_results),
            "status": person_status,
        })

    trace["multi_hop_ms"] = _tick_ms(t)

    search_mode = "multi_hop" if discovered and hop2_status == "ok" else "multi_hop_hop1_only"

    return {
        "search_results": merged or hop1_results,
        "search_mode": search_mode,
        "search_mode_hyde": "",
        "entity_mode": "multi_hop",
        "matched_entities": seed_entities + discovered,
        "per_entity_counts": per_entity_counts,
        "hop_plan": "discovery",
        "hop_trace": hop_trace,
        "fallback_info": fallback_info,
    }


def _tick_ms(t0: float) -> int:
    return round((time.monotonic() - t0) * 1000)
