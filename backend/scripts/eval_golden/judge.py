"""LLM judge support for golden-set evaluation."""

import json
import re
import time

from .common import _compose_final_score, _verdict
from .judge_cache import get_cached_judge_result, put_judge_result


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


def _apply_llm_judge(
    row: dict,
    chat_model: str,
    api_key: str,
    base_url: str,
    cache_path: str | None = None,
    cache_lookup_only: bool = False,
    apply_score: bool = True,
) -> bool:
    cached = get_cached_judge_result(row, chat_model=chat_model, cache_path=cache_path)
    if cached:
        row["judge_cache_status"] = "cached"
        row["judge_cache_hit"] = True
        row["judge_cache_usage"] = "score" if apply_score else "lookup_only"
        if apply_score:
            _apply_judge_result(row, cached)
        else:
            row["cached_judge"] = cached
            row["cached_judge_score"] = cached.get("score")
        return True

    row["judge_cache_status"] = "miss"
    row["judge_cache_hit"] = False
    row["judge_cache_usage"] = "lookup_only" if cache_lookup_only else "score"
    if cache_lookup_only:
        return False

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
    if "error" in judge:
        row["judge_cache_status"] = "error"
    else:
        try:
            put_judge_result(row, chat_model=chat_model, judge_result=judge, cache_path=cache_path)
        except OSError as exc:
            row["judge_cache_error"] = f"cache write failed: {exc}"
        row["judge_cache_status"] = "fresh"
    row["judge_cache_usage"] = "score"

    _apply_judge_result(row, judge)
    return "error" not in judge


def _apply_judge_result(row: dict, judge: dict) -> None:
    row["judge"] = judge
    if "error" in judge:
        citation_score = _citation_score_for_judge(row)
        row["judge_error"] = f"judge error: {judge['error']}"
        row["judge_score"] = None
        row["final_score"] = round(citation_score, 4)
        row["verdict"] = _verdict(row["final_score"])
        return

    judge_score = judge.get("score", 0)
    citation_score = _citation_score_for_judge(row)
    row["judge_score"] = judge_score
    row["final_score"] = _compose_final_score(judge_score, citation_score)
    row["verdict"] = judge.get("verdict", _verdict(row["final_score"]))
    row.pop("unscored_reason", None)


def _citation_score_for_judge(row: dict) -> float:
    value = row.get("citation_score")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    expected_docs = row.get("expected_docs") or row.get("expected_documents") or []
    return 1.0 if not expected_docs else 0.0
