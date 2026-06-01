"""Golden-set evaluation package."""

from .cases import filter_by_slice, filter_quick_cases, load_golden_set
from .citation import compute_chunk_hit_at_k, compute_hit_at_k, score_citation
from .client import query_rag
from .common import EVAL_MODES, normalize_eval_mode
from .judge import _apply_llm_judge, _call_llm_judge, _parse_judge_response, run_judge
from .runner import (
    _case_error_row,
    _case_query_config,
    _get_eval_type,
    query_retrieval_only,
    run_eval,
    run_eval_case,
    run_retrieval_only_case,
)
from .scorers import score_answer_lite, score_no_answer, score_rule
from .summary import build_summary, print_summary

__all__ = [
    "EVAL_MODES",
    "_apply_llm_judge",
    "_call_llm_judge",
    "_case_error_row",
    "_case_query_config",
    "_get_eval_type",
    "_parse_judge_response",
    "build_summary",
    "compute_chunk_hit_at_k",
    "compute_hit_at_k",
    "filter_by_slice",
    "filter_quick_cases",
    "load_golden_set",
    "normalize_eval_mode",
    "print_summary",
    "query_rag",
    "query_retrieval_only",
    "run_eval",
    "run_eval_case",
    "run_judge",
    "run_retrieval_only_case",
    "score_answer_lite",
    "score_citation",
    "score_no_answer",
    "score_rule",
]
