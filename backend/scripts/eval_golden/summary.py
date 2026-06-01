"""Summary and terminal reporting for golden-set evaluation."""

import math
from collections import Counter

from .common import FAILURE_CATEGORIES, _boolish, normalize_eval_mode
from .runner import _row_failure_categories


def _infer_eval_mode(results: list[dict]) -> str:
    for row in results:
        mode = row.get("eval_mode")
        if mode:
            return normalize_eval_mode(str(mode))
    return "full"


def build_summary(
    results: list[dict],
    mode: str | None = None,
    output_path: str = "",
    summary_path: str = "",
) -> dict:
    """Build structured summary with per-type breakdown."""
    eval_mode = normalize_eval_mode(mode or _infer_eval_mode(results))
    scored = [r for r in results if r.get("final_score") is not None]

    if not scored:
        overall = _empty_overall()
        return {
            "mode": eval_mode,
            "flavor": _summary_flavor(results),
            "case_count": len(results),
            "scored_count": 0,
            "unscored": len(results),
            "passed": 0,
            "warning": 0,
            "failed": _summary_failed_count(results),
            "timeout_count": _summary_timeout_count(results),
            "failure_categories": _failure_category_counts(results),
            "hit_at_5": None,
            "hit_at_10": None,
            "citation_hit_rate": None,
            "answer_pass_rate": None,
            "latency_p50_ms": None,
            "latency_p95_ms": None,
            "output_path": str(output_path or ""),
            "summary_path": str(summary_path or ""),
            "overall": overall,
            "per_breakdown": {},
            "per_flavor": {},
            "per_tag": {},
            "per_strict": None,
            "low_score_cases": [],
        }

    scores = [r["final_score"] for r in scored]
    hit_scored = [r for r in scored if r.get("hit_metric_applicable")]
    overall = {
        "count": len(scored),
        "avg_score": round(sum(scores) / len(scores), 4),
        "pass_rate": round(sum(1 for s in scores if s >= 0.8) / len(scores), 4),
        "hit_eval_count": len(hit_scored),
        "hit_at_5_rate": round(sum(1 for r in hit_scored if r.get("hit_at_5")) / len(hit_scored), 4) if hit_scored else None,
        "hit_at_10_rate": round(sum(1 for r in hit_scored if r.get("hit_at_10")) / len(hit_scored), 4) if hit_scored else None,
    }

    latencies = _summary_latencies(scored)
    if latencies:
        overall["p50_latency_ms"] = _percentile_ms(latencies, 0.50)
        overall["p95_latency_ms"] = _percentile_ms(latencies, 0.95)

    per_breakdown = {}
    for etype in ["rule", "llm_judge", "no_answer"]:
        tr = [r for r in scored if r.get("eval_type") == etype]
        if not tr:
            continue
        ts = [r["final_score"] for r in tr]
        per_breakdown[etype] = {
            "count": len(tr),
            "avg_score": round(sum(ts) / len(ts), 4),
            "pass_rate": round(sum(1 for s in ts if s >= 0.8) / len(ts), 4),
        }

    # Per-flavor breakdown
    per_flavor = {}
    for flavor in ["balanced", "exact", "recall", "discovery"]:
        fr = [r for r in scored if _actual_or_requested_flavor(r) == flavor]
        if not fr:
            continue
        fs = [r["final_score"] for r in fr]
        fr_hit = [r for r in fr if r.get("hit_metric_applicable")]
        per_flavor[flavor] = {
            "count": len(fr),
            "avg_score": round(sum(fs) / len(fs), 4),
            "pass_rate": round(sum(1 for s in fs if s >= 0.8) / len(fs), 4),
            "hit_eval_count": len(fr_hit),
            "hit_at_5_rate": round(sum(1 for r in fr_hit if r.get("hit_at_5")) / len(fr_hit), 4) if fr_hit else None,
            "hit_at_10_rate": round(sum(1 for r in fr_hit if r.get("hit_at_10")) / len(fr_hit), 4) if fr_hit else None,
        }

    # Per-tag breakdown
    all_tags = sorted({t for r in scored for t in r.get("tags", [])})
    per_tag = {}
    for tag in all_tags:
        tr = [r for r in scored if tag in r.get("tags", [])]
        if not tr:
            continue
        ts = [r["final_score"] for r in tr]
        tr_hit = [r for r in tr if r.get("hit_metric_applicable")]
        per_tag[tag] = {
            "count": len(tr),
            "avg_score": round(sum(ts) / len(ts), 4),
            "pass_rate": round(sum(1 for s in ts if s >= 0.8) / len(ts), 4),
            "hit_eval_count": len(tr_hit),
            "hit_at_5_rate": round(sum(1 for r in tr_hit if r.get("hit_at_5")) / len(tr_hit), 4) if tr_hit else None,
            "hit_at_10_rate": round(sum(1 for r in tr_hit if r.get("hit_at_10")) / len(tr_hit), 4) if tr_hit else None,
        }

    # Strict evidence slice
    strict_r = [r for r in scored if _actual_or_requested_strict(r)]
    per_strict = {}
    if strict_r:
        ss = [r["final_score"] for r in strict_r]
        strict_hit = [r for r in strict_r if r.get("hit_metric_applicable")]
        per_strict = {
            "count": len(strict_r),
            "avg_score": round(sum(ss) / len(ss), 4),
            "pass_rate": round(sum(1 for s in ss if s >= 0.8) / len(ss), 4),
            "hit_eval_count": len(strict_hit),
            "hit_at_5_rate": round(sum(1 for r in strict_hit if r.get("hit_at_5")) / len(strict_hit), 4) if strict_hit else None,
            "hit_at_10_rate": round(sum(1 for r in strict_hit if r.get("hit_at_10")) / len(strict_hit), 4) if strict_hit else None,
        }

    low = [r for r in scored if r["final_score"] < 0.6]
    low_cases = []
    for r in low:
        reason = "low score"
        if r.get("numeric_misses"):
            reason = f"numeric miss: {r['numeric_misses']}"
        elif r.get("keyword_miss"):
            reason = f"keyword miss: {r['keyword_miss']}"
        elif r.get("must_miss"):
            reason = f"must_have miss: {r['must_miss']}"
        elif r.get("forbidden_hits"):
            reason = f"forbidden: {r['forbidden_hits']}"
        elif r.get("error"):
            reason = str(r["error"])[:80]
        elif r.get("judge_error"):
            reason = str(r["judge_error"])[:80]
        low_cases.append({"id": r["id"], "score": r["final_score"], "reason": reason})
        categories = _row_failure_categories(r)
        low_cases[-1]["failure_category"] = categories[0] if categories else "none"
        low_cases[-1]["failure_categories"] = categories

    return {
        "mode": eval_mode,
        "flavor": _summary_flavor(results),
        "case_count": len(results),
        "scored_count": len(scored),
        "unscored": len(results) - len(scored),
        "passed": sum(1 for s in scores if s >= 0.8),
        "warning": sum(1 for s in scores if 0.5 <= s < 0.8),
        "failed": _summary_failed_count(results),
        "timeout_count": _summary_timeout_count(results),
        "failure_categories": _failure_category_counts(results),
        "hit_at_5": overall["hit_at_5_rate"],
        "hit_at_10": overall["hit_at_10_rate"],
        "citation_hit_rate": _citation_hit_rate(scored, eval_mode),
        "answer_pass_rate": None if eval_mode == "retrieval_only" else overall["pass_rate"],
        "latency_p50_ms": overall.get("p50_latency_ms"),
        "latency_p95_ms": overall.get("p95_latency_ms"),
        "output_path": str(output_path or ""),
        "summary_path": str(summary_path or ""),
        "overall": overall,
        "per_breakdown": per_breakdown,
        "per_flavor": per_flavor,
        "per_tag": per_tag,
        "per_strict": per_strict,
        "low_score_cases": low_cases,
    }


def _empty_overall() -> dict:
    return {
        "count": 0,
        "avg_score": None,
        "pass_rate": None,
        "hit_eval_count": 0,
        "hit_at_5_rate": None,
        "hit_at_10_rate": None,
        "p50_latency_ms": None,
        "p95_latency_ms": None,
    }


def _summary_flavor(results: list[dict]) -> str:
    flavors = sorted({_actual_or_requested_flavor(row) for row in results if row})
    if not flavors:
        return ""
    return flavors[0] if len(flavors) == 1 else "mixed"


def _summary_failed_count(results: list[dict]) -> int:
    failed = 0
    for row in results:
        score = row.get("final_score")
        if row.get("error"):
            failed += 1
        elif score is not None and score < 0.5:
            failed += 1
    return failed


def _summary_timeout_count(results: list[dict]) -> int:
    return sum(1 for row in results if "timed out" in str(row.get("error") or "").lower())


def _failure_category_counts(results: list[dict]) -> dict:
    counts = Counter()
    for row in results:
        for category in _row_failure_categories(row):
            counts[category] += 1
    ordered = {category: counts[category] for category in FAILURE_CATEGORIES if counts[category]}
    for category in sorted(set(counts) - set(ordered)):
        ordered[category] = counts[category]
    return ordered


def _summary_latencies(results: list[dict]) -> list[int]:
    values = []
    for row in results:
        trace = row.get("trace") if isinstance(row.get("trace"), dict) else {}
        value = (
            _positive_ms(trace.get("total_ms"))
            or _positive_ms(row.get("retrieval_latency_ms"))
            or _positive_ms(trace.get("retrieval_wall_ms"))
        )
        if value is not None:
            values.append(value)
    return sorted(values)


def _positive_ms(value) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return int(round(number))


def _percentile_ms(sorted_values: list[int], percentile: float) -> int | None:
    if not sorted_values:
        return None
    idx = max(0, min(math.ceil(len(sorted_values) * percentile) - 1, len(sorted_values) - 1))
    return sorted_values[idx]


def _citation_hit_rate(scored: list[dict], eval_mode: str) -> float | None:
    if eval_mode == "retrieval_only":
        return None
    cited = [
        row for row in scored
        if row.get("citation_score") is not None and row.get("expected_documents")
    ]
    if not cited:
        return None
    return round(sum(1 for row in cited if float(row.get("citation_score") or 0) >= 1.0) / len(cited), 4)


def print_summary(results: list[dict]):
    """Terminal summary."""
    summary = build_summary(results)

    print("\n" + "=" * 60)
    print("EVAL SUMMARY")
    print("=" * 60)
    print(f"Mode: {summary.get('mode', 'full')}")

    o = summary["overall"]
    if not o.get("count"):
        pending = [r for r in results if _is_pending_judge_row(r)]
        print(f"\n  Overall: 0 scored questions")
        if pending:
            print(f"  Pending LLM judge: {len(pending)} questions (use --judge)")
        print()
        return

    print(f"\n  Overall: {o['count']} questions, "
          f"avg={o['avg_score']:.3f}, pass_rate={o['pass_rate']:.1%}, "
          f"hit@5={_fmt_rate(o.get('hit_at_5_rate'))}, "
          f"hit@10={_fmt_rate(o.get('hit_at_10_rate'))}, "
          f"hit_n={o.get('hit_eval_count', 0)}")
    if o.get("p95_latency_ms"):
        print(f"    p95 latency: {o['p95_latency_ms']}ms")

    for etype, bd in summary["per_breakdown"].items():
        print(f"\n  --- {etype} ---")
        print(f"    count={bd['count']}, avg={bd['avg_score']:.3f}, "
              f"pass_rate={bd['pass_rate']:.1%}")

    # Per-flavor summary
    if summary.get("per_flavor"):
        print(f"\n  --- per flavor ---")
        for flavor, fd in summary["per_flavor"].items():
            print(f"    {flavor}: count={fd['count']}, avg={fd['avg_score']:.3f}, "
                  f"pass={fd['pass_rate']:.1%}, "
                  f"hit@5={_fmt_rate(fd.get('hit_at_5_rate'))}, "
                  f"hit@10={_fmt_rate(fd.get('hit_at_10_rate'))}, "
                  f"hit_n={fd.get('hit_eval_count', 0)}")

    # Per-tag summary
    if summary.get("per_tag"):
        print(f"\n  --- per tag ---")
        for tag, td in summary["per_tag"].items():
            print(f"    {tag}: count={td['count']}, avg={td['avg_score']:.3f}, "
                  f"pass={td['pass_rate']:.1%}")

    if summary.get("failure_categories"):
        print(f"\n  --- failure categories ---")
        for category, count in summary["failure_categories"].items():
            print(f"    {category}: {count}")

    # Strict evidence slice
    if summary.get("per_strict"):
        sd = summary["per_strict"]
        print(f"\n  --- strict_evidence ---")
        print(f"    count={sd['count']}, avg={sd['avg_score']:.3f}, "
              f"pass={sd['pass_rate']:.1%}")

    if summary["low_score_cases"]:
        print(f"\n  Low score (<0.6):")
        for lc in summary["low_score_cases"]:
            print(f"    {lc['id']} score={lc['score']:.2f} — {lc['reason']}")

    pending = [r for r in results if _is_pending_judge_row(r)]
    if pending:
        print(f"\n  Pending LLM judge: {len(pending)} questions (use --judge)")

    print()


def _fmt_rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _is_pending_judge_row(row: dict) -> bool:
    return (
        row.get("eval_mode") in {"full", "quick"}
        and row.get("eval_type") == "llm_judge"
        and row.get("final_score") is None
    )


def _actual_or_requested_flavor(row: dict) -> str:
    return row.get("actual_retrieval_flavor") or row.get("preferred_flavor") or "balanced"


def _actual_or_requested_strict(row: dict) -> bool:
    if row.get("actual_strict_evidence") is not None:
        return _boolish(row.get("actual_strict_evidence"))
    return _boolish(row.get("strict_evidence", False))
