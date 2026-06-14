"""HyDE search: LLM generates hypothetical doc → dense search."""

from __future__ import annotations

import logging
import re

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph.state import RunnableConfig

from app.config import settings
from app.rag.embeddings.dense_embedding import dense_embedding
from app.rag.query.config import get_query_config
from app.rag.query.fallback import (
    REASON_LOW_SCORE_OR_INSUFFICIENT_HITS,
    empty_fallback_info,
    fallback_blocked,
    fallback_used,
)
from app.rag.query.filter_utils import build_acl_expr, combine_filters, get_allowed_ids
from app.rag.query.planner import get_query_plan, plan_allows_entity_fallback, plan_budget
from app.rag.query.search import SEARCH_TIMEOUT
from app.rag.query.state import QueryState, effective_query
from app.rag.vectorstores.general_milvus import COLLECTION_NAME, available_output_fields, client
from app.rag.vectorstores.milvus_hits import SEARCH_OUTPUT_FIELDS, parse_hits

logger = logging.getLogger(__name__)

_hyde_llm = ChatOpenAI(
    model=settings.CHAT_MODEL,
    api_key=settings.DEEPSEEK_API_KEY,
    base_url=settings.DEEPSEEK_BASE_URL,
    timeout=30,
    max_retries=2,
    temperature=settings.HYDE_TEMPERATURE,
    max_tokens=settings.HYDE_MAX_TOKENS,
)

HYDE_PROMPT = """\
你要为企业文档检索生成一段“可能出现在相关制度/文档中的检索文本”。

输出要求：
- 只输出正文，不要标题、编号、解释过程或“以下是假设性回答”等前缀。
- 输出一小段，2-3句，80-160字。
- 保留用户问题中的实体、日期、数字、政策名和关键术语。
- 用户询问精确值但资料未知时，保持保守描述，不要编造具体数值。

示例：
问题：星辰科技项目预算250万需要谁审批？
输出：星辰科技项目管理制度规定项目预算审批权限，预算超过200万元的项目需要CEO审批，并提交董事会备案。

问题：电脑丢了应该怎么处理？
输出：信息安全制度规定设备或笔记本电脑丢失后，应在限定时间内报告信息安全部门，并由安全团队远程擦除设备数据。

问题：星辰科技和远景能源的差旅餐费标准分别是多少？
输出：差旅报销制度列明不同公司的餐费补贴标准，包括星辰科技每餐补贴和每日上限，以及远景能源国内和海外差旅补贴。

问题：星辰科技的API日调用量上限是多少？
输出：API接口规范可能只规定每分钟限流、错误码或版本管理要求；若未列明日调用量上限，相关文本应保持为限流口径说明。

用户问题：{query}
输出："""

_HYDE_PREAMBLE_RE = re.compile(
    r"^\s*(?:"
    r"以下是(?:一段)?假设性回答|"
    r"假设性回答|"
    r"以下是可能出现在相关文档中的(?:假设性)?文本|"
    r"可能的文档内容|"
    r"输出"
    r")\s*[:：]\s*",
    re.IGNORECASE,
)


def hyde_search_node(state: QueryState, config: RunnableConfig) -> dict:
    """LLM 生成假设文档 → embedding → dense search。multi_explicit 模式下关闭。"""
    cfg = get_query_config(config)
    plan = get_query_plan(state, config)
    if not plan.get("use_hyde", cfg.use_hyde):
        return {"search_results_hyde": [], "search_mode_hyde": "disabled", "fallback_info": empty_fallback_info()}

    # multi_explicit: HyDE 无法按 entity 分流，跳过
    if state.get("entity_mode") == "multi_explicit":
        return {"search_results_hyde": [], "search_mode_hyde": "disabled_multi", "fallback_info": empty_fallback_info()}

    query = effective_query(state)
    entity_filter = state.get("entity_filter") or None
    original_entity_filter = entity_filter
    budget = plan_budget(state, config)
    hyde_limit = int(budget.get("hyde_limit") or cfg.hyde_limit)

    # ACL filter
    allowed = get_allowed_ids(config)
    if allowed is not None and not allowed:
        return {"search_results_hyde": [], "fallback_info": empty_fallback_info()}
    acl_filter = build_acl_expr(allowed) if allowed else None
    entity_filter = combine_filters(entity_filter, acl_filter)

    # 1. 生成假设文档
    try:
        response = _hyde_llm.invoke([HumanMessage(content=HYDE_PROMPT.format(query=query))])
        hypothetical_doc = normalize_hyde_text(str(response.content or ""))
    except Exception:
        logger.warning("HyDE LLM call failed, returning empty", exc_info=True)
        return {"search_results_hyde": [], "fallback_info": empty_fallback_info()}

    # 2. embed (query + 假设文档)
    hyde_text = f"{query}\n{hypothetical_doc}"
    try:
        hyde_dense = dense_embedding.embed_query(hyde_text)
    except Exception:
        logger.warning("HyDE embedding failed, returning empty", exc_info=True)
        return {"search_results_hyde": [], "fallback_info": empty_fallback_info()}

    # 3. 纯 dense search（带 entity filter fallback）
    try:
        results = client.search(
            collection_name=COLLECTION_NAME,
            data=[hyde_dense],
            anns_field="dense",
            search_params={"metric_type": "COSINE"},
            limit=hyde_limit,
            filter=entity_filter,
            output_fields=available_output_fields(SEARCH_OUTPUT_FIELDS),
            timeout=SEARCH_TIMEOUT,
        )
        hits = parse_hits(results[0])
        mode = "hyde_filtered" if entity_filter else "hyde"
        need_fb = original_entity_filter and (
            len(hits) < cfg.entity_filter_min_results
            or max((h["score"] for h in hits), default=0) < cfg.entity_filter_min_score
        )
        info = empty_fallback_info()
        if need_fb:
            if plan_allows_entity_fallback(state, config):
                logger.info(
                    "HyDE filtered: %d results, max_score=%.3f, retrying unfiltered",
                    len(hits), max((h["score"] for h in hits), default=0),
                )
                results = client.search(
                    collection_name=COLLECTION_NAME,
                    data=[hyde_dense],
                    anns_field="dense",
                    search_params={"metric_type": "COSINE"},
                    limit=hyde_limit,
                    filter=acl_filter,
                    output_fields=available_output_fields(SEARCH_OUTPUT_FIELDS),
                    timeout=SEARCH_TIMEOUT,
                )
                hits = parse_hits(results[0])
                mode = "hyde_filtered_fallback_unfiltered"
                info = fallback_used(original_entity_filter, REASON_LOW_SCORE_OR_INSUFFICIENT_HITS)
            else:
                info = fallback_blocked(original_entity_filter)
    except Exception:
        logger.warning("HyDE Milvus search failed, returning empty", exc_info=True)
        return {"search_results_hyde": [], "search_mode_hyde": "hyde_failed", "fallback_info": empty_fallback_info()}

    logger.debug("HyDE search mode: %s (%d hits)", mode, len(hits))
    return {"search_results_hyde": hits, "search_mode_hyde": mode, "fallback_info": info}


def normalize_hyde_text(text: str) -> str:
    """Strip common model preambles before embedding HyDE text."""
    normalized = (text or "").strip()
    normalized = re.sub(r"^```(?:\w+)?\s*", "", normalized)
    normalized = re.sub(r"\s*```$", "", normalized).strip()
    previous = None
    while previous != normalized:
        previous = normalized
        normalized = _HYDE_PREAMBLE_RE.sub("", normalized).strip()
    return normalized
