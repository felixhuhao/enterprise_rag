"""Helpers for normalized per-query observability payloads."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from typing import Any, cast, overload

TIMING_KEY_LABELS = {
    "entity_confirm_ms": "entity_confirm",
    "query_plan_ms": "query_plan",
    "rewrite_ms": "rewrite",
    "search_hyde_ms": "hyde",
    "query_expansion_ms": "query_expansion",
    "rrf_fusion_ms": "rrf_fusion",
    "table_expand_ms": "table_expand",
    "rerank_ms": "rerank",
    "post_rerank_fallback_ms": "post_rerank_fallback",
    "diversify_context_ms": "diversify_context",
    "context_expand_ms": "context_expand",
    "multi_hop_ms": "multi_hop",
    "build_prompt_ms": "prompt_build",
    "citation_validation_ms": "citation_validation",
    "groundedness_ms": "groundedness",
    "retrieval_wall_ms": "retrieval_wall",
    "first_token_ms": "first_token",
    "generate_ms": "generate",
    "total_ms": "total",
}


def build_query_observability_payload(
    *,
    endpoint: str = "",
    status: str = "success",
    error_code: str = "",
    state: Mapping[str, Any] | None = None,
    trace: Mapping[str, Any] | None = None,
    gen_trace: Mapping[str, Any] | None = None,
    query_config: Any | Mapping[str, Any] | None = None,
    citations: Sequence[Mapping[str, Any]] | None = None,
    fallback_info: Mapping[str, Any] | None = None,
    token_usage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the stable Phase 12 observability payload from query artifacts."""
    state_dict = _dict(state)
    trace_dict = _dict(trace if trace is not None else state_dict.get("trace"))
    gen_trace_dict = _dict(gen_trace)
    plan = _dict(state_dict.get("query_plan"))
    fallback = _dict(fallback_info if fallback_info is not None else state_dict.get("fallback_info"))
    citation_rows = _list_of_dicts(citations if citations is not None else state_dict.get("citations"))

    settings = _resolved_settings(state_dict, plan, query_config)
    result_shape = _result_shape(state_dict, citation_rows, error_code)
    token = _token_usage(token_usage)

    return {
        "endpoint": endpoint or "",
        "status": status or "success",
        "error_code": error_code or "",
        "retrieval_flavor": settings.get("retrieval_flavor", "balanced"),
        "strict_evidence": bool(settings.get("strict_evidence", False)),
        "timings_ms": _timings(trace_dict, gen_trace_dict),
        "resolved_settings": settings,
        "result_shape": result_shape,
        "fallback_info": _jsonable(fallback),
        "token_usage": token,
    }


def observability_json_columns(payload: Mapping[str, Any] | None) -> dict[str, str]:
    """Convert a normalized payload into query_run_stats JSON column values."""
    data = _dict(payload)
    return {
        "endpoint": str(data.get("endpoint") or ""),
        "timings_json": json_dumps(data.get("timings_ms") or {}),
        "settings_json": json_dumps(data.get("resolved_settings") or {}),
        "result_shape_json": json_dumps(data.get("result_shape") or {}),
        "fallback_json": json_dumps(data.get("fallback_info") or {}),
        "token_usage_json": json_dumps(data.get("token_usage") or {}),
    }


def json_dumps(value: Any) -> str:
    """Serialize JSON with a conservative fallback for non-JSON values."""
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True)


def _timings(trace: Mapping[str, Any], gen_trace: Mapping[str, Any]) -> dict[str, int]:
    merged: dict[str, Any] = {}
    merged.update(trace)
    merged.update(gen_trace)

    out: dict[str, int] = {}
    for key, value in merged.items():
        normalized = TIMING_KEY_LABELS.get(str(key))
        if not normalized:
            if str(key).endswith("_ms"):
                normalized = str(key)[:-3]
            elif str(key) == "total":
                normalized = "total"
            else:
                continue
        ms = _int_ms(value)
        if ms is not None:
            out[normalized] = ms
    return out


def _resolved_settings(
    state: Mapping[str, Any],
    plan: Mapping[str, Any],
    query_config: Any | Mapping[str, Any] | None,
) -> dict[str, Any]:
    budget = _dict(plan.get("budget"))
    cfg = _config_dict(query_config)
    flavor = str(plan.get("retrieval_flavor") or cfg.get("retrieval_flavor") or "balanced")
    strict = _bool(plan.get("strict_evidence", cfg.get("strict_evidence", False)))

    selected_entities = _list(state.get("matched_entities"))
    confirmed = str(state.get("confirmed_entity") or "")
    if confirmed and confirmed not in selected_entities:
        selected_entities = [confirmed, *selected_entities]

    dense_weight = _float(cfg.get("dense_weight"), 0.0)
    sparse_weight = _float(cfg.get("sparse_weight"), 0.0)

    return _compact({
        "retrieval_flavor": flavor,
        "strict_evidence": strict,
        "entity_mode": state.get("entity_mode") or "none",
        "selected_entities": selected_entities,
        "fallback_policy": _dict(plan.get("fallback_policy")),
        "budget": budget,
        "search_limit": budget.get("search_limit") or cfg.get("search_limit"),
        "hyde_limit": budget.get("hyde_limit") or cfg.get("hyde_limit"),
        "rrf_top_k": budget.get("rrf_top_k") or cfg.get("rrf_max_results"),
        "rerank_candidate_k": budget.get("rerank_candidate_k") or cfg.get("rerank_max_top_k"),
        "final_context_k": budget.get("final_context_k") or cfg.get("rerank_max_top_k"),
        "max_context_chars": budget.get("max_context_chars"),
        "budget_reason": budget.get("reason"),
        "use_hybrid": dense_weight > 0 and sparse_weight > 0,
        "use_hyde": plan.get("use_hyde", cfg.get("use_hyde")),
        "use_query_expansion": plan.get("use_query_expansion", cfg.get("use_query_expansion")),
        "use_multi_hop": plan.get("use_multi_hop", cfg.get("use_multi_hop")),
        "use_rerank": cfg.get("use_rerank"),
        "use_table_expand": cfg.get("use_table_expand"),
        "use_context_expand": cfg.get("use_context_expand"),
    })


def _result_shape(
    state: Mapping[str, Any],
    citations: Sequence[Mapping[str, Any]],
    error_code: str,
) -> dict[str, Any]:
    final_results = _list_of_dicts(state.get("search_results"))
    has_rerank_candidates = "rerank_candidates" in state
    rerank_candidates = _list_of_dicts(state.get("rerank_candidates"))
    rerank_debug = _list_of_dicts(state.get("rerank_debug"))
    retrieved_source = rerank_candidates if has_rerank_candidates else final_results
    scores = [_float(row.get("final_score"), None) for row in rerank_debug]
    scores = [score for score in scores if score is not None]

    final_doc_ids = _distinct_doc_ids(final_results)
    citation_doc_ids = _distinct_doc_ids(citations)
    empty_reason = ""
    if not final_results:
        empty_reason = error_code or str(state.get("search_mode") or "no_search_results")

    shape = _compact({
        "retrieved_chunks_count": len(retrieved_source),
        "rerank_candidates_count": len(rerank_candidates) if has_rerank_candidates else len(rerank_debug),
        "final_context_chunks_count": len(final_results),
        "citations_count": len(citations),
        "retrieved_documents_count": len(final_doc_ids),
        "cited_documents_count": len(citation_doc_ids),
        "avg_rerank_score": round(sum(scores) / len(scores), 4) if scores else None,
        "top_rerank_score": round(scores[0], 4) if scores else None,
        "context_map_entries": len(_dict(state.get("context_map"))),
    })
    shape["empty_result_reason"] = empty_reason
    return shape


def _token_usage(token_usage: Mapping[str, Any] | None) -> dict[str, Any]:
    data = _dict(token_usage)
    prompt_tokens = _int_or_none(data.get("prompt_tokens"))
    completion_tokens = _int_or_none(data.get("completion_tokens"))
    total_tokens = _int_or_none(data.get("total_tokens"))
    return {
        "available": any(value is not None for value in (prompt_tokens, completion_tokens, total_tokens)),
        "model": data.get("model") or data.get("model_name") or "",
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _distinct_doc_ids(rows: Sequence[Mapping[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for row in rows:
        doc_id = row.get("document_id") or row.get("file_title") or row.get("source")
        if doc_id:
            ids.add(str(doc_id))
    return ids


def _config_dict(query_config: Any | Mapping[str, Any] | None) -> dict[str, Any]:
    if query_config is None:
        return {}
    if isinstance(query_config, Mapping):
        return dict(query_config)
    if is_dataclass(query_config) and not isinstance(query_config, type):
        return asdict(cast(Any, query_config))
    if hasattr(query_config, "__dict__"):
        return dict(query_config.__dict__)
    return {}


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _int_ms(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return max(0, int(round(float(value))))
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@overload
def _float(value: Any, default: float) -> float: ...


@overload
def _float(value: Any, default: None) -> float | None: ...


def _float(value: Any, default: float | None = 0.0) -> float | None:
    if isinstance(value, bool) or value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _compact(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _jsonable(val)
        for key, val in value.items()
        if val not in (None, "", [], {})
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted(str(item) for item in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
