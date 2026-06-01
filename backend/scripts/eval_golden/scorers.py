"""Deterministic golden-set scorers."""

import re

from .common import _compose_final_score, _verdict
from .citation import _citation_output_fields, _expected_documents, score_citation
from .numeric import FINANCIAL_UNIT_PATTERN, _has_refusal_signal, _keyword_in_answer, score_numeric


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
