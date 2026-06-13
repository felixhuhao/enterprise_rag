"""Offline replay harness for the Design 2B intent classifier."""

from __future__ import annotations

import argparse
import dataclasses
import json
import random
import sqlite3
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.rag.query.config import QueryConfig
from app.rag.query.control.budget import resolve_budget_profile
from app.rag.query.control.inferred import CONFIDENCE_LEVELS, Confidence, InferredSignals, merge_intent
from app.rag.query.control.llm_classifier import LlmMarkers, classify_intent_llm
from app.rag.query.control.routing import (
    activatable as route_activatable,
    decision_execution_dict,
    derive_routing_decision,
)

_BREADTH_TO_FLAVOR = {
    "precise": "exact",
    "balanced": "balanced",
    "broad": "recall",
    "discovery": "discovery",
}


@dataclass(frozen=True)
class ReplayCase:
    row_id: int
    query: str
    created_at: str
    entity_mode: str
    selected_entities: list[str]
    breadth: str
    policy: dict[str, Any]
    infra: dict[str, Any]
    deterministic: InferredSignals
    logged_design1_decision: dict[str, Any]
    sample_bucket: str


def main() -> None:
    args = _parse_args()
    rows = _load_rows(args.db, since=args.since)
    cases, skipped = _select_cases(
        rows,
        high_sample_size=args.high_sample_size,
        limit=args.limit,
        seed=args.seed,
    )
    results = _run_cases(cases, concurrency=args.concurrency, delay=args.delay)
    output_path = Path(args.output or _default_output_path())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in results:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    summary = build_summary(results, total_rows=len(rows), skipped=skipped)
    summary_path = output_path.with_name(f"{output_path.stem}_summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Loaded rows: {len(rows)}")
    print(f"Replayed rows: {len(results)}")
    print(f"Skipped: {dict(skipped)}")
    print(f"Results saved to {output_path}")
    print(f"Summary saved to {summary_path}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay Design 2B intent classifier over query_run_stats")
    parser.add_argument("--db", default=settings.DATABASE_PATH, help="SQLite database path")
    parser.add_argument("--output", default=None, help="Output JSONL path")
    parser.add_argument("--since", default=None, help="Only replay rows at/after this created_at value")
    parser.add_argument("--limit", type=int, default=0, help="Maximum rows to replay")
    parser.add_argument("--concurrency", type=int, default=2, help="Classifier concurrency")
    parser.add_argument("--delay", type=float, default=0.0, help="Seconds to wait between submissions")
    parser.add_argument("--high-sample-size", type=int, default=25, help="High-confidence control sample size")
    parser.add_argument("--seed", type=int, default=13, help="Random seed for high-confidence sampling")
    return parser.parse_args()


def _load_rows(db_path: str, *, since: str | None = None) -> list[dict[str, Any]]:
    query = "SELECT id, query, settings_json, created_at FROM query_run_stats"
    params: tuple[Any, ...] = ()
    if since:
        query += " WHERE created_at >= ?"
        params = (since,)
    query += " ORDER BY created_at DESC"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def _select_cases(
    rows: list[dict[str, Any]],
    *,
    high_sample_size: int,
    limit: int,
    seed: int,
) -> tuple[list[ReplayCase], Counter]:
    selected: list[ReplayCase] = []
    high_control: list[ReplayCase] = []
    skipped: Counter = Counter()

    for row in rows:
        case, reason = replay_case_from_row(row)
        if case is None:
            skipped[reason or "invalid"] += 1
            continue
        if case.deterministic.confidence in {"medium", "low"}:
            selected.append(case)
        elif case.deterministic.confidence == "high":
            high_control.append(dataclasses.replace(case, sample_bucket="high_control"))
        else:
            skipped["unsupported_confidence"] += 1

    rng = random.Random(seed)
    rng.shuffle(high_control)
    sampled_high = high_control[:max(0, high_sample_size)]
    unsampled_high = max(0, len(high_control) - len(sampled_high))
    if unsampled_high:
        skipped["unsampled_high"] += unsampled_high
    selected.extend(sampled_high)

    if limit and limit > 0 and len(selected) > limit:
        skipped["limit"] += len(selected) - limit
        selected = selected[:limit]
    return selected, skipped


def replay_case_from_row(row: dict[str, Any]) -> tuple[ReplayCase | None, str | None]:
    settings_json = _json_obj(row.get("settings_json"))
    trace = _dict(settings_json.get("routing_trace"))
    if not trace:
        return None, "no_routing_trace"

    intent = _dict(trace.get("intent"))
    policy = _dict(trace.get("policy"))
    infra = _dict(trace.get("infra"))
    logged_decision = _dict(trace.get("routing_decision"))
    if not intent:
        return None, "no_intent"
    if not policy:
        return None, "no_policy"
    if not infra:
        return None, "no_infra"
    if not logged_decision:
        return None, "no_logged_decision"

    confidence = _confidence(intent.get("confidence"))
    entity_scope = str(intent.get("entity_scope") or "")
    if confidence is None:
        return None, "unsupported_confidence"
    if entity_scope not in {"single", "multi", "broad", "none"}:
        return None, "unsupported_entity_scope"

    breadth = str(policy.get("retrieval_breadth") or settings_json.get("retrieval_breadth") or "")
    if breadth not in _BREADTH_TO_FLAVOR:
        return None, "unsupported_breadth"

    deterministic = InferredSignals(
        entity_scope=entity_scope,
        needs_synthesis=_bool(intent.get("needs_synthesis")),
        needs_discovery=_bool(intent.get("needs_discovery")),
        needs_multi_hop=_bool(intent.get("needs_multi_hop")),
        requested_format=None,
        confidence=confidence,
        reasons=[str(reason) for reason in _list(intent.get("reasons"))],
        source=str(intent.get("source") or "deterministic"),
        fallback_used=_bool(intent.get("fallback_used")),
    )
    return ReplayCase(
        row_id=int(row.get("id") or 0),
        query=str(row.get("query") or ""),
        created_at=str(row.get("created_at") or ""),
        entity_mode=str(settings_json.get("entity_mode") or "none"),
        selected_entities=[str(entity) for entity in _list(settings_json.get("selected_entities"))],
        breadth=breadth,
        policy=policy,
        infra=infra,
        deterministic=deterministic,
        logged_design1_decision=logged_decision,
        sample_bucket=confidence,
    ), None


def _run_cases(cases: list[ReplayCase], *, concurrency: int, delay: float) -> list[dict[str, Any]]:
    if concurrency <= 1:
        results = []
        for case in cases:
            results.append(replay_case(case))
            if delay > 0:
                time.sleep(delay)
        return results

    results: list[dict[str, Any] | None] = [None] * len(cases)
    with ThreadPoolExecutor(max_workers=max(1, min(concurrency, 16))) as executor:
        futures = {}
        for index, case in enumerate(cases):
            futures[executor.submit(replay_case, case)] = index
            if delay > 0:
                time.sleep(delay)
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return [row for row in results if row is not None]


def replay_case(case: ReplayCase) -> dict[str, Any]:
    llm = classify_intent_llm(case.query, case.deterministic)
    merged = merge_intent(case.deterministic, llm)
    replay_cfg = replay_query_config(case)
    budget = resolve_budget_profile(
        case.breadth,
        merged.entity_scope,
        merged.needs_synthesis,
        replay_cfg,
    )
    merged_decision = derive_routing_decision(
        merged,
        case.breadth,
        replay_cfg,
        budget_reason=budget.reason,
    )
    det_execution = decision_execution_dict(case.logged_design1_decision)
    merged_execution = decision_execution_dict(merged_decision)
    diverged = merged_execution != det_execution
    activatable_diverged = llm is not None and diverged and route_activatable(merged)

    return {
        "id": case.row_id,
        "created_at": case.created_at,
        "query": case.query,
        "sample_bucket": case.sample_bucket,
        "entity_mode": case.entity_mode,
        "selected_entities": case.selected_entities,
        "entity_scope": case.deterministic.entity_scope,
        "det_markers": _intent_markers(case.deterministic),
        "llm_markers": dataclasses.asdict(llm) if llm is not None else None,
        "merged": dataclasses.asdict(merged),
        "fallback_used": merged.fallback_used,
        "det_decision": case.logged_design1_decision,
        "merged_decision": dataclasses.asdict(merged_decision),
        "det_execution": det_execution,
        "merged_execution": merged_execution,
        "diverged": diverged,
        "activatable": activatable_diverged,
    }


def replay_query_config(case: ReplayCase) -> QueryConfig:
    return QueryConfig(
        retrieval_flavor=_BREADTH_TO_FLAVOR.get(case.breadth, "balanced"),
        strict_evidence=_bool(case.policy.get("strict_evidence")),
        use_hyde=_bool(case.infra.get("enable_hyde")),
        use_query_expansion=_bool(case.infra.get("enable_query_expansion")),
        use_multi_hop=_bool(case.infra.get("enable_multi_hop")),
    )


def build_summary(results: list[dict[str, Any]], *, total_rows: int, skipped: Counter) -> dict[str, Any]:
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_rows": total_rows,
        "replayed_rows": len(results),
        "skipped": dict(skipped),
        "coverage_rate": _rate(len(results), total_rows),
        "overall": _metric_block(results),
        "by_bucket": {
            bucket: _metric_block([row for row in results if row.get("sample_bucket") == bucket])
            for bucket in ("medium", "low", "high_control")
        },
    }


def _metric_block(rows: list[dict[str, Any]]) -> dict[str, Any]:
    llm_rows = [row for row in rows if row.get("llm_markers") is not None]
    medium_low = [
        row for row in llm_rows
        if row.get("det_markers", {}).get("confidence") in {"medium", "low"}
    ]
    return {
        "count": len(rows),
        "llm_success_count": len(llm_rows),
        "fallback_rate": _rate(sum(1 for row in rows if row.get("fallback_used")), len(rows)),
        "confidence_lift_rate": _rate(
            sum(1 for row in medium_low if row.get("merged", {}).get("confidence") == "high"),
            len(medium_low),
        ),
        "shadow_divergence_rate": _rate(sum(1 for row in rows if row.get("diverged")), len(rows)),
        "activatable_divergence_rate": _rate(sum(1 for row in rows if row.get("activatable")), len(rows)),
        "dimension_disagreement_rates": {
            field: _rate(
                sum(
                    1 for row in llm_rows
                    if row.get("det_markers", {}).get(field) != row.get("merged", {}).get(field)
                ),
                len(llm_rows),
            )
            for field in ("needs_synthesis", "needs_discovery", "needs_multi_hop")
        },
    }


def _intent_markers(intent: InferredSignals) -> dict[str, Any]:
    return {
        "needs_synthesis": intent.needs_synthesis,
        "needs_discovery": intent.needs_discovery,
        "needs_multi_hop": intent.needs_multi_hop,
        "confidence": intent.confidence,
        "reasons": intent.reasons,
    }


def _default_output_path() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return str(Path("data") / f"intent_2b_replay_{stamp}.jsonl")


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _json_obj(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _confidence(value: Any) -> Confidence | None:
    return value if value in CONFIDENCE_LEVELS else None


if __name__ == "__main__":
    main()
