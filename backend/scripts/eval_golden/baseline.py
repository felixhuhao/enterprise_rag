"""Accepted-baseline storage and delta calculation for eval summaries."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path


BASELINE_SCHEMA_VERSION = 1
DELTA_METRICS = (
    "hit_at_10",
    "citation_hit_rate",
    "answer_pass_rate",
    "p95_latency_ms",
    "timeout_count",
)
LOWER_IS_BETTER = {"p95_latency_ms", "timeout_count"}


def default_baseline_path() -> Path:
    backend_dir = Path(__file__).resolve().parents[2]
    data_dir = backend_dir / "data"
    if not data_dir.is_dir():
        data_dir = backend_dir.parent / "data"
    return data_dir / "eval_results" / "accepted_baselines.json"


def attach_baseline_delta(summary: dict, baseline_path: str | Path | None = None) -> dict:
    entry = load_accepted_baseline(summary, baseline_path=baseline_path)
    path = Path(baseline_path) if baseline_path else default_baseline_path()
    if not entry:
        summary["baseline"] = {
            "available": False,
            "path": str(path),
            "mode": summary.get("mode", ""),
            "flavor": summary.get("flavor", ""),
        }
        summary["baseline_delta"] = None
        return summary

    baseline_summary = entry.get("summary") if isinstance(entry.get("summary"), dict) else {}
    summary["baseline"] = {
        "available": True,
        "path": str(path),
        "accepted_at": entry.get("accepted_at", ""),
        "mode": entry.get("mode", ""),
        "flavor": entry.get("flavor", ""),
    }
    summary["baseline_delta"] = _build_delta(summary, baseline_summary)
    return summary


def save_accepted_baseline(summary: dict, baseline_path: str | Path | None = None) -> dict:
    path = Path(baseline_path) if baseline_path else default_baseline_path()
    store = _load_store(path)
    key = _summary_key(summary)
    entry = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "accepted_at": datetime.now(timezone.utc).isoformat(),
        "mode": summary.get("mode", ""),
        "flavor": summary.get("flavor", ""),
        "summary": _baseline_summary_copy(summary),
    }
    store.setdefault("baselines", {})[key] = entry
    _save_store(path, store)
    return entry


def load_accepted_baseline(summary: dict, baseline_path: str | Path | None = None) -> dict | None:
    path = Path(baseline_path) if baseline_path else default_baseline_path()
    store = _load_store(path)
    entry = store.get("baselines", {}).get(_summary_key(summary))
    return entry if isinstance(entry, dict) else None


def _build_delta(current: dict, baseline: dict) -> dict:
    return {
        "overall": _metric_deltas(_overall_metrics(current), _overall_metrics(baseline)),
        "per_flavor": _per_flavor_deltas(current, baseline),
    }


def _overall_metrics(summary: dict) -> dict:
    return {
        "hit_at_10": summary.get("hit_at_10"),
        "citation_hit_rate": summary.get("citation_hit_rate"),
        "answer_pass_rate": summary.get("answer_pass_rate"),
        "p95_latency_ms": summary.get("latency_p95_ms"),
        "timeout_count": summary.get("timeout_count"),
    }


def _flavor_metrics(metric: dict) -> dict:
    return {
        "hit_at_10": metric.get("hit_at_10_rate"),
        "citation_hit_rate": metric.get("citation_hit_rate"),
        "answer_pass_rate": metric.get("answer_pass_rate", metric.get("pass_rate")),
        "p95_latency_ms": metric.get("p95_latency_ms"),
        "timeout_count": metric.get("timeout_count"),
    }


def _per_flavor_deltas(current: dict, baseline: dict) -> dict:
    current_flavors = current.get("per_flavor") if isinstance(current.get("per_flavor"), dict) else {}
    baseline_flavors = baseline.get("per_flavor") if isinstance(baseline.get("per_flavor"), dict) else {}
    flavors = sorted(set(current_flavors) & set(baseline_flavors))
    return {
        flavor: _metric_deltas(_flavor_metrics(current_flavors[flavor]), _flavor_metrics(baseline_flavors[flavor]))
        for flavor in flavors
    }


def _metric_deltas(current: dict, baseline: dict) -> dict:
    values = {}
    for metric in DELTA_METRICS:
        current_value = _number_or_none(current.get(metric))
        baseline_value = _number_or_none(baseline.get(metric))
        delta = None
        if current_value is not None and baseline_value is not None:
            delta = round(current_value - baseline_value, 4)
        values[metric] = {
            "current": current_value,
            "baseline": baseline_value,
            "delta": delta,
            "direction": "lower_is_better" if metric in LOWER_IS_BETTER else "higher_is_better",
        }
    return values


def _summary_key(summary: dict) -> str:
    return f"{summary.get('mode', '')}::{summary.get('flavor', '')}"


def _baseline_summary_copy(summary: dict) -> dict:
    copied = copy.deepcopy(summary)
    copied.pop("baseline", None)
    copied.pop("baseline_delta", None)
    return copied


def _load_store(path: Path) -> dict:
    if not path.is_file():
        return {"schema_version": BASELINE_SCHEMA_VERSION, "baselines": {}}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": BASELINE_SCHEMA_VERSION, "baselines": {}}
    if not isinstance(parsed, dict):
        return {"schema_version": BASELINE_SCHEMA_VERSION, "baselines": {}}
    baselines = parsed.get("baselines")
    if not isinstance(baselines, dict):
        baselines = {}
    return {"schema_version": BASELINE_SCHEMA_VERSION, "baselines": baselines}


def _save_store(path: Path, store: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _number_or_none(value) -> float | int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number.is_integer():
        return int(number)
    return round(number, 4)
