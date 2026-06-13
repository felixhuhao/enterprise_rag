"""Offline shadow-gate report for Design 2C-2 inline shadow."""

from __future__ import annotations

import argparse
import json
import sqlite3
from typing import Any

from app.config import settings


def aggregate_inline_shadow(shadows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate inline_shadow dicts into the 2C-3 gate metrics."""
    ran = [shadow for shadow in shadows if shadow.get("ran")]
    total = len(ran)

    def rate(n: int) -> float:
        return round(n / total, 4) if total else 0.0

    reasons = [str(shadow.get("fallback_reason", "none")) for shadow in ran]
    timeouts = sum(1 for reason in reasons if reason == "timeout")
    errors = sum(1 for reason in reasons if reason == "error")
    parse_fails = sum(1 for reason in reasons if reason == "parse_fail")

    latencies = sorted(int(shadow.get("latency_ms", 0)) for shadow in ran)
    p95 = latencies[int(round(0.95 * (len(latencies) - 1)))] if latencies else 0

    activatable_count = sum(1 for shadow in ran if shadow.get("activatable_diverged"))
    proposal = sum(1 for shadow in ran if shadow.get("proposal_diverged"))

    summary: dict[str, Any] = {
        "volume": total,
        "classifier_error_rate": rate(timeouts + errors),
        "parse_fail_rate": rate(parse_fails),
        "fallback_rate": rate(timeouts + errors + parse_fails),
        "latency_ms_p95": p95,
        "proposal_divergence_rate": rate(proposal),
        "activatable_divergence_rate": rate(activatable_count),
    }
    summary["gates"] = {
        "classifier_error_rate<=0.01": summary["classifier_error_rate"] <= 0.01,
        "parse_fail_rate<=0.02": summary["parse_fail_rate"] <= 0.02,
        "latency_ms_p95<=6000": summary["latency_ms_p95"] <= 6000,
        "volume>=200": total >= 200,
    }
    return summary


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


def _load_shadows(db_path: str, *, since: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (all_shadows, activatable_rows) from query_run_stats."""
    query = "SELECT id, query, settings_json, created_at FROM query_run_stats"
    params: tuple[Any, ...] = ()
    if since:
        query += " WHERE created_at >= ?"
        params = (since,)
    query += " ORDER BY created_at DESC"

    shadows: list[dict[str, Any]] = []
    activatable_rows: list[dict[str, Any]] = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for row in conn.execute(query, params):
            trace = _json_obj(_json_obj(row["settings_json"]).get("routing_trace"))
            shadow = _json_obj(trace.get("inline_shadow"))
            if not shadow:
                continue
            shadows.append(shadow)
            if shadow.get("activatable_diverged"):
                activatable_rows.append(
                    {"id": row["id"], "query": row["query"], "inline_shadow": shadow}
                )
    return shadows, activatable_rows


def main() -> None:
    args = _parse_args()
    shadows, activatable_rows = _load_shadows(args.db, since=args.since)
    summary = aggregate_inline_shadow(shadows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nactivatable_diverged rows for manual audit: {len(activatable_rows)}")
    for row in activatable_rows[: args.audit_limit]:
        print(json.dumps(row, ensure_ascii=False))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report Design 2C-2 inline-shadow gate")
    parser.add_argument("--db", default=settings.DATABASE_PATH, help="SQLite database path")
    parser.add_argument("--since", default=None, help="Only rows at/after this created_at")
    parser.add_argument("--audit-limit", type=int, default=50, help="Max activatable rows to print")
    return parser.parse_args()


if __name__ == "__main__":
    main()
