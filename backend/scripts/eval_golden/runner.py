"""Golden-set eval execution and per-case result shaping."""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Empty, Queue
from threading import Event, Thread

from app.utils.schema import ensure_dict

from . import client, judge
from .citation import (
    _apply_hit_metrics,
    _case_slices,
    _citation_output_fields,
    _expected_behavior,
    _expected_chunk_keys,
    _expected_documents,
    is_hit_metric_applicable,
    score_citation,
)
from .common import FAILURE_CATEGORIES, _boolish, _normalize_flavor, _verdict, normalize_eval_mode
from .scorers import score_answer_lite, score_no_answer, score_rule


def _get_eval_type(item: dict) -> str:
    """Determine eval type from item, with backward compat."""
    if "eval_type" in item:
        return item["eval_type"]
    if item.get("question_type") == "no_answer":
        return "no_answer"
    if item.get("scoring_mode") == "manual":
        return "llm_judge"
    return "rule"


def _case_query_config(item: dict) -> dict:
    """Build the query config that should be used for one golden-set case."""
    source_config = ensure_dict(item.get("source_config"))
    flavor = (
        item.get("preferred_flavor")
        or source_config.get("retrieval_flavor")
        or item.get("retrieval_flavor")
        or "balanced"
    )
    return {
        "retrieval_flavor": _normalize_flavor(flavor),
        "strict_evidence": _boolish(item.get("strict_evidence", source_config.get("strict_evidence", False))),
    }


def run_eval(
    golden_set: list[dict],
    api_base: str,
    token: str,
    delay: float = 1.0,
    progress_callback=None,
    case_timeout_sec: int = 180,
    judge_config: dict | None = None,
    mode: str = "full",
    concurrency: int = 0,
):
    mode = normalize_eval_mode(mode)
    concurrency = _eval_concurrency(mode, concurrency)
    results: list[dict | None] = [None] * len(golden_set)

    if concurrency <= 1:
        for i, item in enumerate(golden_set):
            row = _run_eval_case_with_timeout(
                item,
                i,
                len(golden_set),
                api_base,
                token,
                progress_callback,
                case_timeout_sec=case_timeout_sec,
                judge_config=judge_config,
                mode=mode,
            )
            results[i] = row
            if delay > 0:
                time.sleep(delay)
        return [row for row in results if row is not None]

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {}
        for i, item in enumerate(golden_set):
            future = executor.submit(
                _run_eval_case_with_timeout,
                item,
                i,
                len(golden_set),
                api_base,
                token,
                progress_callback,
                case_timeout_sec,
                judge_config,
                mode,
            )
            futures[future] = i
            if delay > 0:
                time.sleep(delay)

        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except Exception as exc:
                results[index] = _case_error_row(golden_set[index], exc, mode=mode)

    return [row for row in results if row is not None]


def _eval_concurrency(mode: str, concurrency: int = 0) -> int:
    try:
        requested = int(concurrency)
    except (TypeError, ValueError):
        requested = 0
    if requested > 0:
        return max(1, min(requested, 16))
    return 4 if mode == "retrieval_only" else 2


def _run_eval_case_with_timeout(
    item: dict,
    index: int,
    total: int,
    api_base: str,
    token: str,
    progress_callback=None,
    case_timeout_sec: int = 180,
    judge_config: dict | None = None,
    mode: str = "full",
) -> dict:
    result_queue: Queue[dict] = Queue(maxsize=1)
    active = Event()
    active.set()

    def _safe_progress(event: dict) -> None:
        if active.is_set() and progress_callback:
            progress_callback(event)

    def _target() -> None:
        if mode == "retrieval_only":
            result_queue.put(run_retrieval_only_case(item, index, total, _safe_progress))
        else:
            result_queue.put(run_eval_case(
                item,
                index,
                total,
                api_base,
                token,
                _safe_progress,
                judge_config=judge_config,
                mode=mode,
            ))

    worker = Thread(target=_target, daemon=True)
    worker.start()
    try:
        return result_queue.get(timeout=max(0.001, float(case_timeout_sec)))
    except Empty:
        active.clear()
        exc = TimeoutError(f"case timed out after {case_timeout_sec}s")
        row = _case_error_row(item, exc, mode=mode)
        print(f"  CASE TIMEOUT: {row['error']}")
        if progress_callback:
            progress_callback({
                "type": "case_finished",
                "index": index + 1,
                "total": total,
                "row": row,
            })
        return row


def query_retrieval_only(question: str, config: dict) -> dict:
    """Run retrieval-test service locally without answer generation."""
    from app.services.retrieval_test_service import run_retrieval_test

    # Iteration 2 keeps retrieval-only aligned with the retrieval-test defaults.
    # Per-case retrieval parameter overrides belong in a later evaluation pass.
    return run_retrieval_test(
        question,
        top_k=10,
        use_hybrid=True,
        use_hyde=True,
        use_rerank=True,
        retrieval_flavor=config["retrieval_flavor"],
        strict_evidence=config["strict_evidence"],
    )


def run_retrieval_only_case(
    item: dict,
    index: int,
    total: int,
    progress_callback=None,
) -> dict:
    qid = item.get("id") or f"case_{index + 1}"
    question = item.get("question", "")
    eval_type = _get_eval_type(item)
    query_config = _case_query_config(item)

    try:
        print(f"[{index + 1}/{total}] {qid} (retrieval_only) {question[:60]}...")
        if progress_callback:
            progress_callback({
                "type": "case_started",
                "index": index + 1,
                "total": total,
                "id": qid,
                "question": question,
            })

        retrieval = query_retrieval_only(question, query_config)
        results = retrieval.get("results", [])
        trace = retrieval.get("trace", {})
        retrieval_latency_ms = trace.get("retrieval_wall_ms")
        if retrieval_latency_ms is not None and trace.get("total_ms") is None:
            trace = {**trace, "total_ms": retrieval_latency_ms}
        row = {
            "id": qid,
            "eval_mode": "retrieval_only",
            "question": question,
            "eval_type": eval_type,
            "expected_answer": item.get("expected_answer", ""),
            "actual_answer": "",
            "actual_citations": [],
            "trace": trace,
            "retrieval_step": retrieval,
            "rerank_results": results,
            "search_mode": retrieval.get("strategy", {}).get("search_mode", ""),
            "error": "",
            "preferred_flavor": query_config["retrieval_flavor"],
            "strict_evidence": query_config["strict_evidence"],
            "requested_config": query_config,
            "actual_retrieval_flavor": retrieval.get("retrieval_flavor") or None,
            "actual_strict_evidence": retrieval.get("strict_evidence"),
            "tags": item.get("tags", []),
            "slices": _case_slices(item),
            "quick": _boolish(item.get("quick", False)),
            "should_answer": item.get("should_answer", True),
            "expected_behavior": _expected_behavior(item),
            "expected_docs": _expected_documents(item),
            "expected_chunk_keys": _expected_chunk_keys(item),
            "entity_mode": retrieval.get("entity_mode", "none"),
            "fallback_info": retrieval.get("fallback_info", {}),
            "retrieval_latency_ms": retrieval_latency_ms,
        }
        _apply_hit_metrics(row, results, item)
        row["final_score"] = (
            1.0 if row.get("hit_at_10") else 0.0
        ) if row.get("hit_metric_applicable") else None
        final_score = row.get("final_score")
        row["verdict"] = _verdict(final_score) if isinstance(final_score, (int, float)) else "not_applicable"
        _apply_failure_category(row)

        if progress_callback:
            progress_callback({
                "type": "case_finished",
                "index": index + 1,
                "total": total,
                "row": row,
            })
        return row
    except Exception as exc:
        row = _case_error_row(item, exc, eval_type=eval_type, query_config=query_config, mode="retrieval_only")
        print(f"  CASE ERROR: {row['error']}")
        if progress_callback:
            progress_callback({
                "type": "case_finished",
                "index": index + 1,
                "total": total,
                "row": row,
            })
        return row


def run_eval_case(
    item: dict,
    index: int,
    total: int,
    api_base: str,
    token: str,
    progress_callback=None,
    judge_config: dict | None = None,
    mode: str = "full",
) -> dict:
    mode = normalize_eval_mode(mode)
    qid = item.get("id") or f"case_{index + 1}"
    question = item.get("question", "")
    eval_type = _get_eval_type(item)
    query_config = _case_query_config(item)

    try:
        print(f"[{index + 1}/{total}] {qid} ({eval_type}) {question[:60]}...")
        if progress_callback:
            progress_callback({
                "type": "case_started",
                "index": index + 1,
                "total": total,
                "id": qid,
                "question": question,
            })

        rag = client.query_rag(api_base, question, token, session_id="eval_session", config=query_config)

        row = {
            "id": qid,
            "eval_mode": mode,
            "question": question,
            "eval_type": eval_type,
            "expected_answer": item.get("expected_answer", ""),
            "actual_answer": rag["answer"],
            "actual_citations": rag["citations"],
            "trace": rag["trace"],
            "retrieval_step": rag["retrieval_step"],
            "rerank_results": rag["rerank_results"],
            "groundedness": rag.get("groundedness", {}),
            "search_mode": rag["search_mode"],
            "error": rag["error"],
            # New fields passthrough
            "preferred_flavor": query_config["retrieval_flavor"],
            "strict_evidence": query_config["strict_evidence"],
            "requested_config": query_config,
            "actual_retrieval_flavor": rag.get("retrieval_flavor") or None,
            "actual_strict_evidence": rag.get("strict_evidence"),
            "tags": item.get("tags", []),
            "slices": _case_slices(item),
            "quick": _boolish(item.get("quick", False)),
            "should_answer": item.get("should_answer", True),
            "expected_behavior": _expected_behavior(item),
            "expected_docs": _expected_documents(item),
            "expected_chunk_keys": _expected_chunk_keys(item),
        }

        _apply_hit_metrics(row, rag["rerank_results"], item)

        if rag["error"]:
            row["final_score"] = 0.0
            row["verdict"] = "error"
            _apply_failure_category(row)
            print(f"  ERROR: {rag['error']}")
            if progress_callback:
                progress_callback({
                    "type": "case_finished",
                    "index": index + 1,
                    "total": total,
                    "row": row,
                })
            return row

        # --- Score by eval_type ---
        if eval_type == "no_answer":
            sr = score_no_answer(rag["answer"], item)
            row.update(sr)
            row["final_score"] = sr["score"]
            print(f"  verdict={sr['verdict']} score={sr['score']}")

        elif eval_type == "rule":
            sr = score_rule(rag["answer"], rag["citations"], item)
            row.update(sr)
            row["final_score"] = sr["final_score"]
            print(f"  answer={sr['answer_score']:.2f} cite={sr['citation_score']:.2f} "
                  f"final={sr['final_score']:.2f}")

        elif eval_type == "llm_judge":
            cite = score_citation(
                rag["citations"],
                _expected_documents(item),
                item.get("min_expected_citations", 1),
                item=item,
            )
            row["citation_score"] = cite["citation_score"]
            row["citation_doc_hits"] = cite["doc_hits"]
            row["citation_matched"] = cite["matched_docs"]
            row.update(_citation_output_fields(cite))
            row["expected_points"] = item.get("expected_points", [])
            print(f"  [answer] {rag['answer'][:200].replace(chr(10), ' ')}...")
            if rag["citations"]:
                files = [c.get("file_title", "?") for c in rag["citations"]]
                print(f"  [citations] {files}")
            if mode == "answer_lite":
                row.update(score_answer_lite(rag["answer"], rag["citations"], item))
                lookup_config = _answer_lite_judge_lookup_config(judge_config)
                if lookup_config:
                    cache_used = judge._apply_llm_judge(
                        row,
                        chat_model=lookup_config["chat_model"],
                        api_key=lookup_config.get("api_key", ""),
                        base_url=lookup_config.get("base_url", ""),
                        cache_path=lookup_config.get("cache_path"),
                        cache_lookup_only=True,
                        apply_score=True,
                    )
                    if cache_used:
                        row["scoring_version"] = "answer_lite_cached_judge_v1"
                if row.get("final_score") is None:
                    print(f"  WARNING: {qid} answer_lite has no deterministic scoring signals")
                else:
                    print(f"  answer_lite={row['final_score']:.2f}")
            elif judge_config:
                judge._apply_llm_judge(
                    row,
                    chat_model=judge_config["chat_model"],
                    api_key=judge_config["api_key"],
                    base_url=judge_config.get("base_url", ""),
                    cache_path=judge_config.get("cache_path"),
                )
            else:
                row["final_score"] = None  # pending judge

        _apply_failure_category(row)
        if progress_callback:
            progress_callback({
                "type": "case_finished",
                "index": index + 1,
                "total": total,
                "row": row,
            })
        return row

    except Exception as exc:
        row = _case_error_row(item, exc, eval_type=eval_type, query_config=query_config, mode=mode)
        print(f"  CASE ERROR: {row['error']}")
        if progress_callback:
            progress_callback({
                "type": "case_finished",
                "index": index + 1,
                "total": total,
                "row": row,
            })
        return row


def _case_error_row(
    item: dict,
    exc: Exception,
    eval_type: str = "",
    query_config: dict | None = None,
    mode: str = "full",
) -> dict:
    query_config = query_config or _case_query_config(item)
    hit_applicable = is_hit_metric_applicable(item)
    row = {
        "id": item.get("id") or "",
        "eval_mode": normalize_eval_mode(mode),
        "question": item.get("question", ""),
        "eval_type": eval_type or _get_eval_type(item),
        "expected_answer": item.get("expected_answer", ""),
        "actual_answer": "",
        "actual_citations": [],
        "trace": {},
        "retrieval_step": {},
        "rerank_results": [],
        "search_mode": "",
        "error": str(exc)[:1000],
        "preferred_flavor": query_config["retrieval_flavor"],
        "strict_evidence": query_config["strict_evidence"],
        "requested_config": query_config,
        "actual_retrieval_flavor": None,
        "actual_strict_evidence": None,
        "tags": item.get("tags", []),
        "slices": _case_slices(item),
        "quick": _boolish(item.get("quick", False)),
        "should_answer": item.get("should_answer", True),
        "expected_behavior": _expected_behavior(item),
        "expected_docs": _expected_documents(item),
        "expected_chunk_keys": _expected_chunk_keys(item),
        "entity_mode": "none",
        "fallback_info": {},
        "retrieval_latency_ms": None,
        "hit_metric_applicable": hit_applicable,
        "doc_hit_at_5": False if _expected_documents(item) and hit_applicable else None,
        "doc_hit_at_10": False if _expected_documents(item) and hit_applicable else None,
        "chunk_hit_at_5": False if _expected_chunk_keys(item) and hit_applicable else None,
        "chunk_hit_at_10": False if _expected_chunk_keys(item) and hit_applicable else None,
        "hit_at_5": False if hit_applicable else None,
        "hit_at_10": False if hit_applicable else None,
        "final_score": 0.0,
        "verdict": "error",
    }
    _apply_failure_category(row)
    return row


def _answer_lite_judge_lookup_config(judge_config: dict | None) -> dict | None:
    if judge_config and judge_config.get("chat_model"):
        return judge_config
    try:
        from app.config import settings
    except Exception:
        return None
    chat_model = getattr(settings, "CHAT_MODEL", "")
    if not chat_model:
        return None
    return {
        "chat_model": chat_model,
        "api_key": "",
        "base_url": getattr(settings, "DEEPSEEK_BASE_URL", ""),
    }


def _apply_failure_category(row: dict) -> None:
    categories = _derive_failure_categories(row)
    row["failure_categories"] = categories
    row["failure_category"] = categories[0] if categories else "none"


def _row_failure_categories(row: dict) -> list[str]:
    categories = row.get("failure_categories")
    if isinstance(categories, list):
        return [str(category) for category in categories if category and category != "none"]
    category = row.get("failure_category")
    if category and category != "none":
        return [str(category)]
    return _derive_failure_categories(row)


def _derive_failure_categories(row: dict) -> list[str]:
    error = str(row.get("error") or "")
    if error:
        return ["timeout"] if "timed out" in error.lower() else ["unknown"]

    score = row.get("final_score")
    if (
        score is None
        and row.get("eval_mode") in {"full", "quick"}
        and row.get("eval_type") == "llm_judge"
    ):
        return ["pending_judge"]
    if score is not None and score >= 0.8:
        return []

    categories = []

    if row.get("eval_type") == "no_answer":
        categories.append("no_answer_wrong")

    rerank_drop = _has_rerank_drop(row)
    if rerank_drop:
        categories.append("rerank_drop")

    if row.get("hit_metric_applicable") and row.get("hit_at_10") is False and not rerank_drop:
        categories.append("retrieval_miss")

    answer_score = row.get("answer_score")
    miss_fields = (
        row.get("numeric_misses")
        or row.get("must_miss")
        or row.get("keyword_miss")
        or row.get("expected_point_miss")
    )
    if (
        isinstance(answer_score, (int, float)) and answer_score < 0.8
    ) or (answer_score is None and miss_fields):
        categories.append("answer_incomplete")

    citation_score = row.get("citation_score")
    if isinstance(citation_score, (int, float)) and citation_score < 1.0:
        categories.append("citation_miss")

    if _has_context_loss(row):
        categories.append("context_loss")

    if _has_unsupported_answer(row):
        categories.append("answer_unsupported")

    if _has_uncertain_judge(row):
        categories.append("judge_uncertain")

    if not categories:
        categories.append("unknown")
    return _ordered_failure_categories(categories)


def _has_rerank_drop(row: dict) -> bool:
    if not row.get("hit_metric_applicable"):
        return False
    return any(
        row.get(key) is True
        for key in ("pre_rerank_hit_at_10", "retrieval_hit_at_10", "candidate_hit_at_10")
    ) and row.get("hit_at_10") is False


def _has_context_loss(row: dict) -> bool:
    if row.get("eval_mode") == "retrieval_only":
        return False
    if not row.get("hit_metric_applicable") or row.get("hit_at_10") is not True:
        return False
    citation_score = row.get("citation_score")
    return isinstance(citation_score, (int, float)) and not isinstance(citation_score, bool) and citation_score < 1.0


def _has_unsupported_answer(row: dict) -> bool:
    judge = ensure_dict(row.get("judge"))
    unsupported = judge.get("unsupported_claims")
    if isinstance(unsupported, list) and unsupported:
        return True

    groundedness = ensure_dict(row.get("groundedness"))
    score = groundedness.get("groundedness_score")
    if isinstance(score, (int, float)) and not isinstance(score, bool) and score < 0.7:
        return True
    claims = groundedness.get("claims")
    if isinstance(claims, list):
        return any(_claim_is_unsupported(claim) for claim in claims if isinstance(claim, dict))
    return False


def _claim_is_unsupported(claim: dict) -> bool:
    value = claim.get("supported")
    if isinstance(value, bool):
        return not value
    status = str(claim.get("status") or claim.get("verdict") or "").lower()
    return status in {"unsupported", "not_supported", "false", "fail"}


def _has_uncertain_judge(row: dict) -> bool:
    if row.get("eval_type") != "llm_judge":
        return False
    if row.get("judge_error"):
        return True
    judge = ensure_dict(row.get("judge"))
    if judge.get("parse_warning"):
        return True
    judge_score = row.get("judge_score")
    if isinstance(judge_score, (int, float)) and not isinstance(judge_score, bool):
        return 0.6 <= judge_score < 0.8
    return str(judge.get("verdict") or "").lower() == "warn"


def _ordered_failure_categories(categories: list[str]) -> list[str]:
    seen = {str(category) for category in categories if category and category != "none"}
    ordered = [category for category in FAILURE_CATEGORIES if category in seen]
    ordered.extend(sorted(seen - set(ordered)))
    return ordered
