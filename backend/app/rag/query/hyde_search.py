"""HyDE search: LLM generates hypothetical doc → dense search."""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph.state import RunnableConfig

from app.config import settings
from app.rag.embeddings.text_embedding_v4 import _text_embedding
from app.rag.query.config import get_query_config
from app.rag.query.state import QueryState
from app.rag.vectorstores.general_milvus import COLLECTION_NAME, client

logger = logging.getLogger(__name__)

OUTPUT_FIELDS = [
    "content",
    "title",
    "section_title",
    "source_type",
    "table_id",
    "table_tokens",
    "raw_table_path",
    "document_id",
    "file_title",
    "entity_name",
    "part",
]

_hyde_llm = ChatOpenAI(
    model=settings.CHAT_MODEL,
    api_key=settings.DASHSCOPE_API_KEY,
    base_url=settings.DASHSCOPE_BASE_URL,
    timeout=30,
    max_retries=2,
    temperature=0.3,
)

HYDE_PROMPT = (
    "请根据以下金融相关问题，生成一段假设性的回答"
    "（包含关键财务指标和数据点，可以使用虚构数据）：\n\n{query}"
)


def hyde_search_node(state: QueryState, config: RunnableConfig) -> dict:
    """LLM 生成假设文档 → embedding → dense search。"""
    cfg = get_query_config(config)
    if not cfg.use_hyde:
        return {"search_results_hyde": []}

    query = state.get("rewritten_query") or state["query"]
    entity_filter = state.get("entity_filter") or None

    # 1. 生成假设文档
    try:
        response = _hyde_llm.invoke([HumanMessage(content=HYDE_PROMPT.format(query=query))])
        hypothetical_doc = response.content
    except Exception:
        logger.warning("HyDE LLM call failed, returning empty", exc_info=True)
        return {"search_results_hyde": []}

    # 2. embed (query + 假设文档)
    hyde_text = f"{query}\n{hypothetical_doc}"
    try:
        hyde_dense = _text_embedding.embed_query(hyde_text)
    except Exception:
        logger.warning("HyDE embedding failed, returning empty", exc_info=True)
        return {"search_results_hyde": []}

    # 3. 纯 dense search
    try:
        results = client.search(
            collection_name=COLLECTION_NAME,
            data=[hyde_dense],
            anns_field="dense",
            search_params={"metric_type": "COSINE"},
            limit=cfg.hyde_limit,
            filter=entity_filter,
            output_fields=OUTPUT_FIELDS,
        )
    except Exception:
        logger.warning("HyDE Milvus search failed, returning empty", exc_info=True)
        return {"search_results_hyde": []}

    hits = []
    for hit in results[0]:
        entity = hit["entity"]
        hits.append({
            "chunk_id": hit.get("id") or hit.get("chunk_id") or entity.get("chunk_id"),
            "document_id": entity.get("document_id", ""),
            "file_title": entity.get("file_title", ""),
            "title": entity.get("title", ""),
            "section_title": entity.get("section_title", ""),
            "source_type": entity.get("source_type", ""),
            "table_id": entity.get("table_id", ""),
            "table_tokens": entity.get("table_tokens"),
            "raw_table_path": entity.get("raw_table_path", ""),
            "content": entity.get("content", ""),
            "part": entity.get("part"),
            "score": hit["distance"],
        })

    logger.debug("HyDE search returned %d hits", len(hits))
    return {"search_results_hyde": hits}
