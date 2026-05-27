"""LLM rerank: batch scoring + score fusion + cliff detection."""

from __future__ import annotations

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph.state import RunnableConfig

from app.config import settings
from app.rag.query.config import get_query_config
from app.rag.query.scoring_utils import cliff_detect
from app.rag.query.state import QueryState

logger = logging.getLogger(__name__)

_rerank_llm = ChatOpenAI(
    model=settings.CHAT_MODEL,
    api_key=settings.DEEPSEEK_API_KEY,
    base_url=settings.DEEPSEEK_BASE_URL,
    timeout=30,
    max_retries=2,
    temperature=0.0,
)

RERANK_SYSTEM = """\
你是一个搜索结果相关性评分器。根据用户问题，对每条检索结果打分（0 到 1）。

评分标准：
- 1.0: 直接回答了问题的具体数据或事实
- 0.7: 包含相关但不够具体的信息
- 0.4: 话题相关但缺少关键信息
- 0.1: 几乎无关

严格按 JSON 数组格式输出，只输出分数数组，不要其他文字。
示例：[0.9, 0.7, 0.3, 0.1]"""


def rerank_node(state: QueryState, config: RunnableConfig) -> dict:
    """LLM batch rerank + score fusion + cliff detection。"""
    cfg = get_query_config(config)
    if not cfg.use_rerank:
        return {"search_results": state.get("search_results", [])}

    results = state.get("search_results", [])
    query = state.get("rewritten_query") or state["query"]

    if not results:
        return {"search_results": [], "rerank_debug": []}

    # 1. LLM batch 打分
    llm_scores = _batch_rerank(query, results, cfg)

    # 2. Score fusion + rerank 字段
    max_rrf = max((r["score"] for r in results), default=1) or 1
    for i, doc in enumerate(results):
        llm_s = llm_scores[i] if i < len(llm_scores) else cfg.rerank_fallback_score
        rrf_normalized = doc["score"] / max_rrf
        final_score = cfg.rerank_llm_weight * llm_s + cfg.rerank_rrf_weight * rrf_normalized
        doc["rerank"] = {
            "llm_score": round(llm_s, 3),
            "rrf_score": round(rrf_normalized, 3),
            "final_score": round(final_score, 3),
        }
        doc["score"] = final_score

    # 3. 排序
    results.sort(key=lambda x: x["score"], reverse=True)

    # 4. 动态 Top-K (cliff detection)
    top_k = cliff_detect(results, cfg)
    results = results[:top_k]

    # 5. rerank_debug（无 content，只保留摘要）
    rerank_debug = [
        {
            "index": i + 1,
            "file_title": doc.get("file_title", ""),
            "section_title": doc.get("section_title", ""),
            "source_type": doc.get("source_type", ""),
            **doc["rerank"],
        }
        for i, doc in enumerate(results[:10])
    ]

    logger.debug("Rerank: %d → %d results", len(llm_scores), len(results))
    return {"search_results": results, "rerank_debug": rerank_debug}


def _batch_rerank(query: str, results: list[dict], cfg) -> list[float]:
    """LLM batch 打分，每批最多 N 条。"""
    all_scores: list[float] = []

    for start in range(0, len(results), cfg.rerank_batch_size):
        batch = results[start:start + cfg.rerank_batch_size]
        docs_text = "\n\n".join(
            f"[{i+1}] {r.get('content', '')[:cfg.content_preview_length]}"
            for i, r in enumerate(batch)
        )
        user_msg = f"用户问题：{query}\n\n检索结果：\n{docs_text}"

        try:
            response = _rerank_llm.invoke([
                SystemMessage(content=RERANK_SYSTEM),
                HumanMessage(content=user_msg),
            ])
            scores = json.loads(response.content.strip())
            if isinstance(scores, list):
                all_scores.extend(float(s) for s in scores)
            else:
                all_scores.extend([cfg.rerank_fallback_score] * len(batch))
        except (json.JSONDecodeError, ValueError, Exception) as e:
            logger.warning("Rerank LLM parse failed: %s", e)
            all_scores.extend([cfg.rerank_fallback_score] * len(batch))

    return all_scores
