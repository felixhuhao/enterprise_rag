"""Shared constants and tiny helpers for golden-set evaluation."""

from app.rag.query.config import normalize_retrieval_flavor as _normalize_flavor

EVAL_MODES = {"full", "quick", "retrieval_only", "answer_lite"}
FAILURE_CATEGORIES = (
    "retrieval_miss",
    "rerank_drop",
    "context_loss",
    "citation_miss",
    "answer_incomplete",
    "answer_unsupported",
    "no_answer_wrong",
    "judge_uncertain",
    "pending_judge",
    "timeout",
    "unknown",
)
ANSWER_COMPONENT_WEIGHT = 0.75
CITATION_COMPONENT_WEIGHT = 0.25


def _verdict(score: float) -> str:
    if score >= 0.8:
        return "pass"
    elif score >= 0.6:
        return "warn"
    return "fail"


def _compose_final_score(answer_component: float, citation_score: float) -> float:
    return round(
        ANSWER_COMPONENT_WEIGHT * answer_component
        + CITATION_COMPONENT_WEIGHT * citation_score,
        4,
    )


def _boolish(value) -> bool:
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def normalize_eval_mode(value: str | None) -> str:
    mode = (value or "full").strip().lower()
    if mode not in EVAL_MODES:
        raise ValueError(f"invalid eval mode: {value}. Expected one of: {', '.join(sorted(EVAL_MODES))}")
    return mode
