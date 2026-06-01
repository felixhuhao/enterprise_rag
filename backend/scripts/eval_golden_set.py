"""
Golden Set 自动化评估脚本 V2

三条评分轴：answer_score, citation_score, (faithfulness via LLM judge)
三种题型：rule, llm_judge, no_answer

用法:
    cd backend
    python scripts/eval_golden_set.py \
        --golden-set ../data/stock_reports_v1_auto.jsonl \
        --api-base http://127.0.0.1:8010/api \
        --output ../data/stock_reports_v1_auto_results.jsonl

    # 启用 LLM judge（用于 llm_judge 题型）
    python scripts/eval_golden_set.py \
        --golden-set ../data/golden_set.jsonl --judge

评估流程:
    golden_set.jsonl → query RAG → collect answer/citations/trace
        → score by eval_type → results.jsonl + summary.json
"""

import argparse
import json
import math
import re
import sys
import time
from collections import Counter
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread

import requests

EVAL_MODES = {"full", "quick", "retrieval_only", "answer_lite"}
FAILURE_CATEGORIES = (
    "retrieval_miss",
    "citation_miss",
    "answer_incomplete",
    "no_answer_wrong",
    "timeout",
    "unknown",
)
ANSWER_COMPONENT_WEIGHT = 0.75
CITATION_COMPONENT_WEIGHT = 0.25

# ---------------------------------------------------------------------------
# SSE consumer
# ---------------------------------------------------------------------------


def query_rag(
    api_base: str,
    question: str,
    token: str,
    session_id: str = "",
    config: dict | None = None,
) -> dict:
    """POST /query/chat/stream，消费 SSE，返回聚合结果。"""
    url = f"{api_base}/query/chat/stream"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
    }
    body = {"query": question, "session_id": session_id, "is_eval": True}
    if config:
        body["config"] = config

    result = {
        "answer": "",
        "citations": [],
        "trace": {},
        "retrieval_step": {},
        "rerank_results": [],
        "search_mode": "",
        "retrieval_flavor": "",
        "strict_evidence": False,
        "error": None,
    }

    with requests.post(url, headers=headers, json=body, stream=True, timeout=120) as resp:
        if resp.status_code != 200:
            result["error"] = f"HTTP {resp.status_code}: {resp.text[:500]}"
            return result

        buffer = ""
        for chunk in resp.iter_content(chunk_size=None, decode_unicode=True):
            if not chunk:
                continue
            buffer += chunk
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if not payload:
                    continue
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                evt_type = event.get("type", "")

                if evt_type == "delta":
                    result["answer"] += event.get("content", "")
                elif evt_type == "citations":
                    result["citations"] = event.get("citations", [])
                elif evt_type == "trace":
                    result["trace"].update(event.get("trace", {}))
                elif evt_type == "retrieval_step":
                    result["retrieval_step"] = {
                        "results_count": event.get("results_count"),
                        "entity": event.get("entity"),
                        "rewritten_query": event.get("rewritten_query"),
                        "search_mode": event.get("search_mode"),
                        "search_mode_hyde": event.get("search_mode_hyde"),
                        "retrieval_flavor": event.get("retrieval_flavor"),
                        "strict_evidence": event.get("strict_evidence"),
                    }
                    result["search_mode"] = event.get("search_mode", "")
                    result["retrieval_flavor"] = event.get("retrieval_flavor", "")
                    result["strict_evidence"] = bool(event.get("strict_evidence", False))
                elif evt_type == "rerank":
                    result["rerank_results"] = event.get("results", [])
                elif evt_type == "error":
                    result["error"] = {
                        "code": event.get("code"),
                        "message": event.get("message"),
                    }
                elif evt_type == "message_end":
                    return result

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


REFUSAL_SIGNALS = [
    "知识库中", "文档中没", "没有找到", "无法提供", "暂无",
    "未包含", "不包含", "未披露", "未发布", "尚无",
    "没有足够", "不在知识库", "无法回答", "未能找到",
    "未提及", "未涉及", "不涉及", "没有提及", "没有涉及",
    "没有相关信息", "无法确认", "没有覆盖", "未覆盖",
    "没有该", "不包含该", "没有关于",
    # LLM 拒绝变体补充
    "没有披露", "尚未发布", "未知", "无法确定",
    "无任何来源", "没有数据", "无法判断",
]

FINANCIAL_UNIT_PATTERN = r"(\d+\.?\d*)\s*(亿元|亿美元|百万美元|万片|%|港币|人民币)"
CHINESE_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
UNIT_ALIASES = {
    "个季度": ["个季度", "季度"],
    "年": ["年"],
    "个月": ["个月", "月"],
    "天": ["天", "日"],
    "个工作日": ["个工作日", "工作日"],
    "小时": ["小时"],
    "分钟": ["分钟", "分"],
    "万元": ["万元", "万"],
    "元": ["元"],
}
NUMBER_PATTERN = r"-?\d[\d,]*(?:\.\d+)?"


def _has_refusal_signal(answer: str) -> bool:
    return any(sig in answer for sig in REFUSAL_SIGNALS)


# ---------------------------------------------------------------------------
# Numeric scoring
# ---------------------------------------------------------------------------

def _parse_chinese_int(value: str) -> int | None:
    """Parse simple Chinese integers used in policy text, up to 99."""
    value = value.strip()
    if not value:
        return None
    if value in CHINESE_DIGITS:
        return CHINESE_DIGITS[value]
    if value == "十":
        return 10
    if "十" in value:
        left, right = value.split("十", 1)
        tens = CHINESE_DIGITS.get(left, 1 if left == "" else None)
        ones = CHINESE_DIGITS.get(right, 0 if right == "" else None)
        if tens is None or ones is None:
            return None
        return tens * 10 + ones
    return None


def _unit_aliases(unit: str) -> list[str]:
    return UNIT_ALIASES.get(unit, [unit] if unit else [])


def _parse_numeric_token(token: str) -> float | None:
    try:
        return float(token.replace(",", ""))
    except ValueError:
        return None


def _numeric_close(found: float, expected: float, tolerance: float) -> bool:
    if expected == 0:
        return found == 0
    return abs(found - expected) / abs(expected) <= tolerance


def _find_number_before_unit(answer: str, unit: str) -> list[float]:
    values: list[float] = []
    for unit_m in re.finditer(re.escape(unit), answer):
        start = max(0, unit_m.start() - 25)
        context = answer[start:unit_m.start()]
        for token in re.findall(NUMBER_PATTERN, context):
            value = _parse_numeric_token(token)
            if value is not None:
                values.append(value)
    return values


def _find_scaled_amount_match(answer: str, expected_val: float, expected_unit: str,
                              tolerance: float) -> bool:
    """Match Yuan/Wan-Yuan variants such as 3万元 == 30,000元."""
    if expected_unit in {"万元", "万"}:
        for unit in ("万元", "万"):
            for found in _find_number_before_unit(answer, unit):
                if _numeric_close(found, expected_val, tolerance):
                    return True
        expected_yuan = expected_val * 10000
        for found in _find_number_before_unit(answer, "元"):
            if _numeric_close(found, expected_yuan, tolerance):
                return True
        return False

    if expected_unit == "元":
        for found in _find_number_before_unit(answer, "元"):
            if _numeric_close(found, expected_val, tolerance):
                return True
        for unit in ("万元", "万"):
            for found in _find_number_before_unit(answer, unit):
                if _numeric_close(found * 10000, expected_val, tolerance):
                    return True
        return False

    return False


def _find_chinese_numeric_match(answer: str, expected_val: float, expected_unit: str,
                                tolerance: float) -> bool:
    if expected_val != int(expected_val):
        return False

    units = _unit_aliases(expected_unit)
    if expected_unit and not units:
        return False

    if expected_unit:
        for unit in units:
            pattern = rf"([零一二两三四五六七八九十]{{1,3}})\s*{re.escape(unit)}"
            for match in re.finditer(pattern, answer):
                found = _parse_chinese_int(match.group(1))
                if found is not None and abs(found - expected_val) <= max(tolerance * abs(expected_val), 0):
                    return True
        return False

    for token in re.findall(r"[零一二两三四五六七八九十]{1,3}", answer):
        found = _parse_chinese_int(token)
        if found is not None and abs(found - expected_val) <= max(tolerance * abs(expected_val), 0):
            return True
    return False


def _find_numeric_match(answer: str, expected_val: float, expected_unit: str,
                        tolerance: float) -> bool:
    """Check if expected_val with unit context appears in answer within tolerance."""
    if expected_unit:
        if expected_unit in {"万元", "万", "元"} and _find_scaled_amount_match(
            answer,
            expected_val,
            expected_unit,
            tolerance,
        ):
            return True

        # Find expected value near occurrences of the unit string or aliases.
        for unit in _unit_aliases(expected_unit):
            for found in _find_number_before_unit(answer, unit):
                if _numeric_close(found, expected_val, tolerance):
                    return True
        if _find_chinese_numeric_match(answer, expected_val, expected_unit, tolerance):
            return True
        return False
    else:
        # No unit constraint — find value anywhere
        for ns in re.findall(NUMBER_PATTERN, answer):
            found = _parse_numeric_token(ns)
            if found is None:
                continue
            if _numeric_close(found, expected_val, tolerance):
                return True
        return _find_chinese_numeric_match(answer, expected_val, expected_unit, tolerance)


def _keyword_variants(keyword: str) -> set[str]:
    variants = {keyword}
    match = re.fullmatch(r"(\d+)(.+)", keyword)
    if not match:
        return variants
    value = int(match.group(1))
    suffix = match.group(2)
    if value == 2:
        variants.add(f"两{suffix}")
    for chinese, parsed in CHINESE_DIGITS.items():
        if parsed == value:
            variants.add(f"{chinese}{suffix}")
    return variants


def _keyword_in_answer(keyword: str, answer: str) -> bool:
    return any(variant in answer for variant in _keyword_variants(keyword))


def score_numeric(answer: str, numeric_expectations: list[dict]) -> dict:
    """Score numeric expectations with relative tolerance."""
    if not numeric_expectations:
        return {"numeric_score": None, "hits": [], "misses": []}

    hits, misses = [], []
    for exp in numeric_expectations:
        val = exp["value"]
        unit = exp.get("unit", "")
        tol = exp.get("tolerance", 0.01)
        label = f"{val}{unit}"
        if _find_numeric_match(answer, val, unit, tol):
            hits.append(label)
        else:
            misses.append(label)

    score = len(hits) / len(numeric_expectations)
    return {"numeric_score": round(score, 4), "hits": hits, "misses": misses}


# ---------------------------------------------------------------------------
# Citation scoring (shared axis)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Slice filtering
# ---------------------------------------------------------------------------


def filter_by_slice(golden_set: list[dict], slices: list[str]) -> list[dict]:
    """Filter golden set items by slice tags.

    Matching logic:
    - slice value matches item's preferred_flavor
    - slice value appears in item's tags
    - special slice 'strict' matches strict_evidence == True
    Multiple slices take union.
    """
    if not slices:
        return golden_set

    filtered = []
    for item in golden_set:
        flavor = item.get("preferred_flavor", "")
        tags = item.get("tags", [])
        case_slices = _case_slices(item)
        strict = item.get("strict_evidence", False)

        for s in slices:
            if s == "strict" and strict:
                filtered.append(item)
                break
            elif s == flavor:
                filtered.append(item)
                break
            elif s in tags or s in case_slices:
                filtered.append(item)
                break

    return filtered


def filter_quick_cases(golden_set: list[dict]) -> list[dict]:
    return [item for item in golden_set if _boolish(item.get("quick", False))]


def normalize_eval_mode(value: str | None) -> str:
    mode = (value or "full").strip().lower()
    if mode not in EVAL_MODES:
        raise ValueError(f"invalid eval mode: {value}. Expected one of: {', '.join(sorted(EVAL_MODES))}")
    return mode


# ---------------------------------------------------------------------------
# Rule scoring
# ---------------------------------------------------------------------------


def score_rule(answer: str, citations: list, item: dict) -> dict:
    """Score rule-based questions: numeric + keyword + citation.

    New schema:  numeric_expectations + must_have + nice_to_have
    Legacy:      expected_keywords  (backward compat)
    """
    expected_docs = item.get("expected_documents", [])
    min_citations = item.get("min_expected_citations", 1)

    # New schema fields
    must_have = item.get("must_have", [])
    nice_to_have = item.get("nice_to_have", [])
    numeric_exps = item.get("numeric_expectations", [])

    # --- Legacy backward compat ---
    if not must_have and not nice_to_have and not numeric_exps:
        expected_kw = item.get("expected_keywords", [])
        kw_hits = [kw for kw in expected_kw if _keyword_in_answer(kw, answer)]
        kw_score = len(kw_hits) / len(expected_kw) if expected_kw else 1.0

        cite = score_citation(citations, expected_docs, min_citations)
        final = 0.7 * kw_score + 0.3 * cite["citation_score"]

        return {
            "answer_score": round(kw_score, 4),
            "citation_score": cite["citation_score"],
            "final_score": round(final, 4),
            "verdict": _verdict(final),
            "keyword_hits": kw_hits,
            "keyword_miss": [kw for kw in expected_kw if kw not in kw_hits],
            "keyword_score": round(kw_score, 4),
            "citation_doc_hits": cite["doc_hits"],
            "citation_matched": cite["matched_docs"],
            **_citation_output_fields(cite),
            "scoring_version": "legacy",
        }

    # --- New scoring ---
    num_result = score_numeric(answer, numeric_exps)
    numeric_score = num_result["numeric_score"] if num_result["numeric_score"] is not None else 0.0

    must_hits = [kw for kw in must_have if _keyword_in_answer(kw, answer)]
    must_score = len(must_hits) / len(must_have) if must_have else 1.0

    nice_hits = [kw for kw in nice_to_have if _keyword_in_answer(kw, answer)]
    nice_score = len(nice_hits) / len(nice_to_have) if nice_to_have else 1.0

    # Answer score composition
    if numeric_exps:
        answer_score = 0.5 * numeric_score + 0.3 * must_score + 0.2 * nice_score
    else:
        answer_score = 0.75 * must_score + 0.25 * nice_score

    # Citation + final
    cite = score_citation(citations, expected_docs, min_citations, item=item)
    final = _compose_final_score(answer_score, cite["citation_score"])

    return {
        "answer_score": round(answer_score, 4),
        "citation_score": cite["citation_score"],
        "final_score": round(final, 4),
        "verdict": _verdict(final),
        "numeric_score": round(numeric_score, 4) if numeric_exps else None,
        "numeric_hits": num_result["hits"],
        "numeric_misses": num_result["misses"],
        "must_hits": must_hits,
        "must_miss": [kw for kw in must_have if kw not in must_hits],
        "nice_hits": nice_hits,
        "citation_doc_hits": cite["doc_hits"],
        "citation_matched": cite["matched_docs"],
        **_citation_output_fields(cite),
        "scoring_version": "v2",
    }


def score_answer_lite(answer: str, citations: list, item: dict) -> dict:
    """Score LLM-judge cases without calling a judge.

    This is intentionally conservative: only deterministic expected-point
    substring hits and citation targets contribute to the score.
    """
    expected_points = [p for p in item.get("expected_points", []) if isinstance(p, str) and p.strip()]
    expected_docs = _expected_documents(item)
    cite = score_citation(citations, expected_docs, item.get("min_expected_citations", 1), item=item)

    point_hits = [point for point in expected_points if _keyword_in_answer(point, answer)]
    point_miss = [point for point in expected_points if point not in point_hits]
    answer_score = round(len(point_hits) / len(expected_points), 4) if expected_points else None

    if answer_score is not None and expected_docs:
        final_score = _compose_final_score(answer_score, cite["citation_score"])
    elif answer_score is not None:
        final_score = answer_score
    elif expected_docs:
        final_score = cite["citation_score"]
    else:
        final_score = None
    unscored_reason = "answer_lite_no_deterministic_signals" if final_score is None else ""

    return {
        "answer_score": answer_score,
        "citation_score": cite["citation_score"] if expected_docs else None,
        "citation_doc_hits": cite["doc_hits"],
        "citation_matched": cite["matched_docs"],
        **_citation_output_fields(cite),
        "expected_point_hits": point_hits,
        "expected_point_miss": point_miss,
        "final_score": final_score,
        "verdict": _verdict(final_score) if final_score is not None else "not_applicable",
        "unscored_reason": unscored_reason,
        "scoring_version": "answer_lite_v1",
    }


# ---------------------------------------------------------------------------
# No-Answer scoring
# ---------------------------------------------------------------------------


def score_no_answer(answer: str, item: dict) -> dict:
    """Score no_answer questions: refusal detection + hallucination check.

    Supports custom forbidden_patterns / forbidden_phrases / allowed_patterns.
    Falls back to built-in logic for out_of_scope_entity / missing_actual_value.
    """
    na_type = item.get("no_answer_type", "missing_actual_value")
    has_refusal = _has_refusal_signal(answer)

    forbidden_patterns = item.get("forbidden_patterns", [])
    allowed_patterns = item.get("allowed_patterns", [])
    forbidden_phrases = item.get("forbidden_phrases", [])

    # --- Custom forbidden patterns (new schema) ---
    if forbidden_patterns or forbidden_phrases:
        fp_hits = []
        for p in forbidden_patterns:
            for m in re.finditer(p, answer):
                text = m.group(0)
                if not any(re.search(a, text) for a in allowed_patterns):
                    fp_hits.append(text)

        phrase_hits = [p for p in forbidden_phrases if re.search(p, answer)]

        if not has_refusal:
            v, s = "fail", 0.0
        elif phrase_hits:
            v, s = "fail", 0.0
        elif fp_hits:
            v, s = "warn", 0.5
        else:
            v, s = "pass", 1.0

        return {
            "verdict": v, "score": s,
            "no_answer_type": na_type,
            "has_refusal_signal": has_refusal,
            "forbidden_hits": fp_hits,
            "forbidden_phrase_hits": phrase_hits,
        }

    # --- Default logic (backward compat) ---
    if na_type == "out_of_scope_entity":
        question = item.get("question", "")
        entity_names = ["华虹半导体", "台积电", "三星", "英特尔", "英伟达"]
        asked_entity = next((en for en in entity_names if en in question), "")

        if asked_entity:
            pat = asked_entity + r".*?" + FINANCIAL_UNIT_PATTERN
            entity_nums = re.findall(pat, answer)
            if entity_nums:
                return {
                    "verdict": "fail", "score": 0.0,
                    "no_answer_type": na_type,
                    "has_refusal_signal": has_refusal,
                    "forbidden_hits": [f"{asked_entity}+{n[0]}{n[1]}" for n in entity_nums],
                }

        if has_refusal:
            return {"verdict": "pass", "score": 1.0,
                    "no_answer_type": na_type,
                    "has_refusal_signal": has_refusal,
                    "forbidden_hits": []}
        return {"verdict": "fail", "score": 0.0,
                "no_answer_type": na_type,
                "has_refusal_signal": has_refusal,
                "forbidden_hits": []}

    else:  # missing_actual_value
        financial_nums = re.findall(FINANCIAL_UNIT_PATTERN, answer)
        has_financial = len(financial_nums) >= 2
        allowed_keywords = item.get("allowed_keywords", [])
        has_allowed = any(kw in answer for kw in allowed_keywords)

        if has_refusal and not has_financial:
            v, s = "pass", 1.0
        elif has_refusal and has_financial and has_allowed:
            v, s = "pass", 0.8
        elif has_refusal:
            v, s = "warn", 0.5
        else:
            v, s = "fail", 0.0

        return {
            "verdict": v, "score": s,
            "no_answer_type": na_type,
            "has_refusal_signal": has_refusal,
            "forbidden_hits": financial_nums if has_financial else [],
        }


# ---------------------------------------------------------------------------
# LLM Judge
# ---------------------------------------------------------------------------

JUDGE_PROMPT = """\
你是一个 RAG 系统评估助手。请综合判断以下回答的质量。

## 问题
{question}

## 期望要点
{expected_points}

## 实际回答
{actual_answer}

## 引用来源
{citations_text}

请综合判断以下三个方面，给出一个总分：
1. 回答是否覆盖了期望要点
2. 是否有明显事实错误
3. 是否有未被引用支撑的具体断言

输出严格 JSON（不要 markdown 代码块）：
{{
  "score": 0.0-1.0,
  "verdict": "pass" | "warn" | "fail",
  "missing_points": ["未覆盖的要点"],
  "unsupported_claims": ["无引用支撑的具体声明"],
  "reason": "一句话说明理由"
}}

评分标准：
- score >= 0.8: pass — 核心要点正确且有引用支撑
- 0.6 <= score < 0.8: warn — 部分缺失或不准确
- score < 0.6: fail — 严重错误或遗漏
"""


def _call_llm_judge(question: str, expected_answer: str, expected_points: list,
                    actual_answer: str, citations: list,
                    chat_model: str, api_key: str, base_url: str) -> dict:
    try:
        from openai import OpenAI
    except ImportError:
        return {"error": "openai package not installed"}

    citations_text = ""
    for c in citations:
        ft = c.get("file_title", "")
        st = c.get("section_title", "")
        citations_text += f"- [{c.get('id', '?')}] {ft}"
        if st:
            citations_text += f" > {st}"
        citations_text += "\n"
    if not citations_text:
        citations_text = "(无引用)"

    points = "\n".join(f"- {p}" for p in expected_points) if expected_points else expected_answer

    prompt = JUDGE_PROMPT.format(
        question=question,
        expected_points=points,
        actual_answer=actual_answer,
        citations_text=citations_text,
    )

    client = OpenAI(api_key=api_key, base_url=base_url)
    last_result: dict = {"error": "judge did not run"}
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=chat_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=500,
            )
            raw = (resp.choices[0].message.content or "").strip()
            last_result = _parse_judge_response(raw)
            if "error" not in last_result:
                return last_result
        except Exception as e:
            last_result = {"error": str(e)}
        if attempt < 2:
            time.sleep(0.5)
    return last_result


def _parse_judge_response(raw: str) -> dict:
    """Parse judge JSON, tolerating code fences or prose around the object."""
    raw = (raw or "").strip()
    if not raw:
        return {"error": "empty judge response"}

    candidates = [raw]
    if raw.startswith("```"):
        fenced = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if fenced.rstrip().endswith("```"):
            fenced = fenced.rstrip()[:-3]
        candidates.append(fenced.strip())

    extracted = _extract_json_object(raw)
    if extracted and extracted not in candidates:
        candidates.append(extracted)

    last_error = ""
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError as exc:
            last_error = str(exc)

    fallback = _parse_judge_score_fallback(raw)
    if fallback:
        fallback["parse_warning"] = last_error or "judge response was not strict JSON"
        fallback["raw_response"] = raw[:500]
        return fallback

    return {"error": last_error or "judge response was not JSON", "raw_response": raw[:500]}


def _extract_json_object(raw: str) -> str:
    start = raw.find("{")
    if start < 0:
        return ""

    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(raw)):
        ch = raw[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return raw[start:idx + 1]
    return raw[start:]


def _parse_judge_score_fallback(raw: str) -> dict | None:
    score_match = re.search(r'"?score"?\s*[:：]\s*([01](?:\.\d+)?)', raw, re.IGNORECASE)
    if not score_match:
        return None
    score = max(0.0, min(1.0, float(score_match.group(1))))
    verdict_match = re.search(r'"?verdict"?\s*[:：]\s*"?\b(pass|warn|fail)\b"?', raw, re.IGNORECASE)
    verdict = verdict_match.group(1).lower() if verdict_match else _verdict(score)
    return {
        "score": score,
        "verdict": verdict,
        "missing_points": [],
        "unsupported_claims": [],
        "reason": "Judge response was not strict JSON; used fallback score parsing.",
    }


def run_judge(results: list[dict], chat_model: str, api_key: str,
              base_url: str, delay: float = 0.5):
    """Run LLM judge on llm_judge questions."""
    to_judge = [r for r in results
                if r.get("eval_type") == "llm_judge" and not r.get("error")]
    if not to_judge:
        print("No llm_judge questions to evaluate.")
        return

    print(f"\nRunning LLM judge on {len(to_judge)} questions...")

    for r in to_judge:
        _apply_llm_judge(r, chat_model=chat_model, api_key=api_key, base_url=base_url)
        if r.get("judge_error"):
            print(f"  {r['id']} {r.get('verdict', '?')} score={r.get('final_score', 0):.2f} | {r['judge_error']}")
        elif r.get("error"):
            print(f"  {r['id']} judge error: {r['error']}")
        else:
            judge = r.get("judge", {})
            print(f"  {r['id']} {r.get('verdict', '?')} score={r.get('judge_score', 0):.2f} | {judge.get('reason', '')[:60]}")

        time.sleep(delay)


def _apply_llm_judge(row: dict, chat_model: str, api_key: str, base_url: str) -> None:
    judge = _call_llm_judge(
        question=row["question"],
        expected_answer=row.get("expected_answer", ""),
        expected_points=row.get("expected_points", []),
        actual_answer=row.get("actual_answer", ""),
        citations=row.get("actual_citations", []),
        chat_model=chat_model,
        api_key=api_key,
        base_url=base_url,
    )
    row["judge"] = judge
    if "error" in judge:
        citation_score = row.get("citation_score", 0)
        row["judge_error"] = f"judge error: {judge['error']}"
        row["judge_score"] = None
        row["final_score"] = round(citation_score, 4)
        row["verdict"] = _verdict(row["final_score"])
        return

    judge_score = judge.get("score", 0)
    citation_score = row.get("citation_score", 0)
    row["judge_score"] = judge_score
    row["final_score"] = _compose_final_score(judge_score, citation_score)
    row["verdict"] = judge.get("verdict", _verdict(row["final_score"]))


# ---------------------------------------------------------------------------
# Eval runner
# ---------------------------------------------------------------------------


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
    source_config = item.get("source_config") if isinstance(item.get("source_config"), dict) else {}
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


def load_golden_set(path: str, *, include_disabled: bool = False) -> list[dict]:
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                item = json.loads(line)
                if include_disabled or item.get("status", "active") != "disabled":
                    items.append(item)
    return items


def run_eval(
    golden_set: list[dict],
    api_base: str,
    token: str,
    delay: float = 1.0,
    progress_callback=None,
    case_timeout_sec: int = 180,
    judge_config: dict | None = None,
    mode: str = "full",
):
    mode = normalize_eval_mode(mode)

    results = []

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
        results.append(row)
        time.sleep(delay)

    return results


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
        row["verdict"] = _verdict(row["final_score"]) if row.get("final_score") is not None else "not_applicable"
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

        rag = query_rag(api_base, question, token, session_id="eval_session", config=query_config)

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
                if row.get("final_score") is None:
                    print(f"  WARNING: {qid} answer_lite has no deterministic scoring signals")
                else:
                    print(f"  answer_lite={row['final_score']:.2f}")
            elif judge_config:
                _apply_llm_judge(
                    row,
                    chat_model=judge_config["chat_model"],
                    api_key=judge_config["api_key"],
                    base_url=judge_config.get("base_url", ""),
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
    if score is not None and score >= 0.8:
        return []

    categories = []

    if row.get("eval_type") == "no_answer":
        categories.append("no_answer_wrong")

    if row.get("hit_metric_applicable") and row.get("hit_at_10") is False:
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

    if not categories:
        categories.append("unknown")
    return _ordered_failure_categories(categories)


def _ordered_failure_categories(categories: list[str]) -> list[str]:
    seen = {str(category) for category in categories if category and category != "none"}
    ordered = [category for category in FAILURE_CATEGORIES if category in seen]
    ordered.extend(sorted(seen - set(ordered)))
    return ordered


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


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


def _normalize_flavor(value: str) -> str:
    return value if value in {"balanced", "exact", "recall", "discovery"} else "balanced"


def _boolish(value) -> bool:
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Golden Set 自动化评估 V2")
    parser.add_argument("--golden-set", required=True, help="JSONL golden set 路径")
    parser.add_argument("--api-base", default="http://127.0.0.1:8010/api",
                        help="API base URL")
    parser.add_argument("--token", default=None, help="API token")
    parser.add_argument("--output", default=None, help="结果 JSONL 路径")
    parser.add_argument("--delay", type=float, default=1.0, help="每题间隔秒数")
    parser.add_argument("--judge", action="store_true", help="启用 LLM judge")
    parser.add_argument("--judge-model", default=None, help="Judge 模型")
    parser.add_argument("--case-timeout", type=int, default=180, help="单题超时秒数")
    parser.add_argument("--mode", default="full", choices=sorted(EVAL_MODES),
                        help="评测模式: full | quick | retrieval_only | answer_lite")
    parser.add_argument("--slice", action="append", default=[],
                        help="按 tag/flavor/strict 过滤: --slice exact --slice recall --slice strict")
    args = parser.parse_args()
    mode = normalize_eval_mode(args.mode)
    needs_token = mode != "retrieval_only"

    # --- Token ---
    token = args.token
    if needs_token:
        if not token:
            try:
                from app.config import settings
                token = settings.API_TOKEN or ""
            except Exception:
                pass
        if not token:
            env_path = Path(__file__).resolve().parent.parent / ".env"
            if env_path.exists():
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("API_TOKEN="):
                        token = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        if not token:
            print("Error: 需要 --token 或在 .env 中配置 API_TOKEN")
            sys.exit(1)
    token = token or ""

    # --- Load ---
    golden_set = load_golden_set(args.golden_set, include_disabled=mode == "quick")
    types = Counter(_get_eval_type(item) for item in golden_set)
    print(f"Loaded {len(golden_set)} questions from {args.golden_set}")
    print(f"  Types: {dict(types)}")
    print(f"  Mode: {mode}")

    # --- Slice filtering ---
    if args.slice:
        golden_set = filter_by_slice(golden_set, args.slice)
        print(f"  Filtered by slice {args.slice}: {len(golden_set)} questions remain")
        if not golden_set:
            print("Error: no questions match the specified slice(s)")
            sys.exit(0)

    if mode == "quick":
        golden_set = filter_quick_cases(golden_set)
        print(f"  Filtered by quick=true: {len(golden_set)} questions remain")
        if not golden_set:
            print("Error: no quick cases found")
            sys.exit(0)

    # --- LLM Judge config (optional, applied per case) ---
    judge_config = None
    if args.judge and mode in {"full", "quick"}:
        judge_model = args.judge_model
        api_key = ""
        base_url = ""
        try:
            from app.config import settings
            if not judge_model:
                judge_model = settings.CHAT_MODEL
            api_key = settings.DEEPSEEK_API_KEY
            base_url = settings.DEEPSEEK_BASE_URL
        except Exception:
            pass
        if not api_key:
            env_path = Path(__file__).resolve().parent.parent / ".env"
            if env_path.exists():
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("DEEPSEEK_API_KEY="):
                        api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    elif line.startswith("DEEPSEEK_BASE_URL="):
                        base_url = line.split("=", 1)[1].strip().strip('"').strip("'")
                    elif line.startswith("CHAT_MODEL=") and not judge_model:
                        judge_model = line.split("=", 1)[1].strip().strip('"').strip("'")

        if not api_key or not judge_model:
            print("Warning: --judge 需要 DEEPSEEK_API_KEY 和 CHAT_MODEL")
        else:
            judge_config = {"chat_model": judge_model, "api_key": api_key, "base_url": base_url}

    # --- Run eval ---
    results = run_eval(
        golden_set,
        args.api_base,
        token,
        delay=args.delay,
        case_timeout_sec=args.case_timeout,
        judge_config=judge_config,
        mode=mode,
    )

    # --- Save results ---
    output_path = args.output
    if not output_path:
        stem = Path(args.golden_set).stem
        output_path = str(Path(args.golden_set).parent / f"{stem}_results.jsonl")

    with open(output_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nResults saved to {output_path}")

    # --- Save summary ---
    base = Path(output_path).stem
    if base.endswith("_results"):
        base = base[:-len("_results")]
    summary_path = str(Path(output_path).parent / f"{base}_summary.json")

    summary = build_summary(results, mode=mode, output_path=output_path, summary_path=summary_path)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"Summary saved to {summary_path}")

    # --- Print terminal summary ---
    print_summary(results)


if __name__ == "__main__":
    main()
