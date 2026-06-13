"""HyDE search: LLM generates hypothetical doc → dense search."""

from __future__ import annotations

import logging

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

HYDE_PROMPT = (
    "请根据以下企业文档问题，生成一段可能出现在相关文档中的假设性文本，80-160字。"
    "覆盖关键术语、实体、时间、数值或结论。不要输出标题、解释过程或前后缀：\n\n{query}"
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
        hypothetical_doc = str(response.content or "").strip()
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
