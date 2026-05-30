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
import re
import sys
import time
from collections import Counter
from pathlib import Path

import requests

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
    body = {"query": question, "session_id": session_id}
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


def _has_refusal_signal(answer: str) -> bool:
    return any(sig in answer for sig in REFUSAL_SIGNALS)


# ---------------------------------------------------------------------------
# Numeric scoring
# ---------------------------------------------------------------------------


def _find_numeric_match(answer: str, expected_val: float, expected_unit: str,
                        tolerance: float) -> bool:
    """Check if expected_val with unit context appears in answer within tolerance."""
    if expected_unit:
        # Find expected value near occurrences of the unit string
        for unit_m in re.finditer(re.escape(expected_unit), answer):
            start = max(0, unit_m.start() - 25)
            context = answer[start:unit_m.end()]
            for ns in re.findall(r"(-?\d+\.?\d*)", context):
                try:
                    found = float(ns)
                except ValueError:
                    continue
                if expected_val == 0:
                    if found == 0:
                        return True
                elif abs(found - expected_val) / abs(expected_val) <= tolerance:
                    return True
        return False
    else:
        # No unit constraint — find value anywhere
        for ns in re.findall(r"(-?\d+\.?\d*)", answer):
            try:
                found = float(ns)
            except ValueError:
                continue
            if expected_val == 0:
                if found == 0:
                    return True
            elif abs(found - expected_val) / abs(expected_val) <= tolerance:
                return True
        return False


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


def is_hit_metric_applicable(item: dict) -> bool:
    """Hit@K applies only to answerable cases with explicit expected docs."""
    return bool(item.get("expected_documents")) and item.get("should_answer", True)


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
        strict = item.get("strict_evidence", False)

        for s in slices:
            if s == "strict" and strict:
                filtered.append(item)
                break
            elif s == flavor:
                filtered.append(item)
                break
            elif s in tags:
                filtered.append(item)
                break

    return filtered


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
        kw_hits = [kw for kw in expected_kw if kw in answer]
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

    must_hits = [kw for kw in must_have if kw in answer]
    must_score = len(must_hits) / len(must_have) if must_have else 1.0

    nice_hits = [kw for kw in nice_to_have if kw in answer]
    nice_score = len(nice_hits) / len(nice_to_have) if nice_to_have else 1.0

    # Answer score composition
    if numeric_exps:
        answer_score = 0.5 * numeric_score + 0.3 * must_score + 0.2 * nice_score
    else:
        answer_score = 0.75 * must_score + 0.25 * nice_score

    # Citation + final
    cite = score_citation(citations, expected_docs, min_citations, item=item)
    final = 0.75 * answer_score + 0.25 * cite["citation_score"]

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

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        resp = client.chat.completions.create(
            model=chat_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=500,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        return json.loads(raw)
    except Exception as e:
        return {"error": str(e)}


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
        judge = _call_llm_judge(
            question=r["question"],
            expected_answer=r.get("expected_answer", ""),
            expected_points=r.get("expected_points", []),
            actual_answer=r.get("actual_answer", ""),
            citations=r.get("actual_citations", []),
            chat_model=chat_model,
            api_key=api_key,
            base_url=base_url,
        )
        r["judge"] = judge

        if "error" in judge:
            print(f"  {r['id']} judge error: {judge['error']}")
        else:
            s = judge.get("score", 0)
            v = judge.get("verdict", "?")
            print(f"  {r['id']} {v} score={s:.2f} | {judge.get('reason', '')[:60]}")

        time.sleep(delay)


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


def load_golden_set(path: str) -> list[dict]:
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def run_eval(golden_set: list[dict], api_base: str, token: str, delay: float = 1.0):
    results = []

    for i, item in enumerate(golden_set):
        qid = item["id"]
        question = item["question"]
        eval_type = _get_eval_type(item)
        query_config = _case_query_config(item)

        print(f"[{i+1}/{len(golden_set)}] {qid} ({eval_type}) {question[:60]}...")

        rag = query_rag(api_base, question, token, session_id="eval_session", config=query_config)

        row = {
            "id": qid,
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
            "should_answer": item.get("should_answer", True),
        }

        # Hit@K from rerank results
        expected_docs = item.get("expected_documents", [])
        hit_applicable = is_hit_metric_applicable(item)
        row["hit_metric_applicable"] = hit_applicable
        row["hit_at_5"] = compute_hit_at_k(rag["rerank_results"], expected_docs, k=5) if hit_applicable else None
        row["hit_at_10"] = compute_hit_at_k(rag["rerank_results"], expected_docs, k=10) if hit_applicable else None

        if rag["error"]:
            row["final_score"] = 0.0
            row["verdict"] = "error"
            print(f"  ERROR: {rag['error']}")
            results.append(row)
            time.sleep(delay)
            continue

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
            # Collect answer + citation score; judge runs later via --judge
            cite = score_citation(
                rag["citations"],
                item.get("expected_documents", []),
                item.get("min_expected_citations", 1),
                item=item,
            )
            row["citation_score"] = cite["citation_score"]
            row["citation_doc_hits"] = cite["doc_hits"]
            row["citation_matched"] = cite["matched_docs"]
            row.update(_citation_output_fields(cite))
            row["expected_points"] = item.get("expected_points", [])
            row["final_score"] = None  # pending judge
            print(f"  [answer] {rag['answer'][:200].replace(chr(10), ' ')}...")
            if rag["citations"]:
                files = [c.get("file_title", "?") for c in rag["citations"]]
                print(f"  [citations] {files}")

        results.append(row)
        time.sleep(delay)

    return results


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def build_summary(results: list[dict]) -> dict:
    """Build structured summary with per-type breakdown."""
    scored = [r for r in results if r.get("final_score") is not None]

    if not scored:
        return {"overall": {"count": 0}, "per_breakdown": {}, "low_score_cases": []}

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

    # p95 latency from trace
    latencies = sorted(r.get("trace", {}).get("total_ms", 0) for r in scored if r.get("trace", {}).get("total_ms"))
    if latencies:
        p95_idx = min(int(len(latencies) * 0.95), len(latencies) - 1)
        overall["p95_latency_ms"] = latencies[p95_idx]

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
        low_cases.append({"id": r["id"], "score": r["final_score"], "reason": reason})

    return {
        "overall": overall,
        "per_breakdown": per_breakdown,
        "per_flavor": per_flavor,
        "per_tag": per_tag,
        "per_strict": per_strict,
        "low_score_cases": low_cases,
    }


def print_summary(results: list[dict]):
    """Terminal summary."""
    summary = build_summary(results)

    print("\n" + "=" * 60)
    print("EVAL SUMMARY")
    print("=" * 60)

    o = summary["overall"]
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

    pending = [r for r in results
               if r.get("eval_type") == "llm_judge" and r.get("final_score") is None]
    if pending:
        print(f"\n  Pending LLM judge: {len(pending)} questions (use --judge)")

    print()


def _fmt_rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


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
    parser.add_argument("--slice", action="append", default=[],
                        help="按 tag/flavor/strict 过滤: --slice exact --slice recall --slice strict")
    args = parser.parse_args()

    # --- Token ---
    token = args.token
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

    # --- Load ---
    golden_set = load_golden_set(args.golden_set)
    types = Counter(_get_eval_type(item) for item in golden_set)
    print(f"Loaded {len(golden_set)} questions from {args.golden_set}")
    print(f"  Types: {dict(types)}")

    # --- Slice filtering ---
    if args.slice:
        golden_set = filter_by_slice(golden_set, args.slice)
        print(f"  Filtered by slice {args.slice}: {len(golden_set)} questions remain")
        if not golden_set:
            print("Error: no questions match the specified slice(s)")
            sys.exit(0)

    # --- Run eval ---
    results = run_eval(golden_set, args.api_base, token, delay=args.delay)

    # --- LLM Judge (optional) ---
    if args.judge:
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
            run_judge(results, judge_model, api_key, base_url)
            # Update final_score for judged questions
            for r in results:
                if (r.get("eval_type") == "llm_judge"
                        and "judge" in r
                        and "error" not in r.get("judge", {})):
                    j = r["judge"]
                    js = j.get("score", 0)
                    cs = r.get("citation_score", 0)
                    r["judge_score"] = js
                    r["final_score"] = round(0.75 * js + 0.25 * cs, 4)
                    r["verdict"] = j.get("verdict", _verdict(r["final_score"]))

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

    summary = build_summary(results)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"Summary saved to {summary_path}")

    # --- Print terminal summary ---
    print_summary(results)


if __name__ == "__main__":
    main()
