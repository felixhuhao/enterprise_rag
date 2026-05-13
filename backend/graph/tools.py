from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from pymilvus import AnnSearchRequest, WeightedRanker
from milvus_db.collections_operator import client, CONTEXT_COLLECTION_NAME
from my_llm import tavily_client, text_embedding
from app.config import settings
from utils.log_utils import log


@tool("search_context", parse_docstring=True)
async def search_context(query: Optional[str] = None, user_name: Optional[str] = None) -> str:
    """
    根据用户的输入，检索与查询相关的历史上下文信息，然后给出正确的回答。

    Args:
        query: (可选)用户刚刚输入的文本内容。
        user_name: (可选)当前的用户名。

    Returns:
        从历史上下文中检索到的结果。

    """
    # 调用 text-embedding-v4 获取嵌入向量
    embedding = text_embedding.embed_query(query)
    filter_expr = ""
    if user_name:
        filter_expr = f'user == "{user_name}"'

    dense_search_params = {"metric_type": "IP", "params": {"nprobe": 10}}
    dense_req = AnnSearchRequest(
        [embedding], "context_dense", dense_search_params, limit=3, expr=filter_expr
    )
    sparse_search_params = {"metric_type": "BM25", "params": {"drop_ratio_search": 0.2}}
    sparse_req = AnnSearchRequest(
        [query], "context_sparse", sparse_search_params, limit=3, expr=filter_expr
    )

    # 混合检索：dense（语义）+ sparse（BM25 关键词），加权融合
    rerank = WeightedRanker(1.0, 1.0)
    res = client.hybrid_search(
        collection_name=CONTEXT_COLLECTION_NAME,
        reqs=[sparse_req, dense_req],
        ranker=rerank,
        limit=3,
        output_fields=["context_text"],
    )

    if not res[0]:
        return "没有找到相关的历史上下文信息。"

    # 用 Milvus 混合检索分数过滤不相关结果（替代 ragas，毫秒级）
    top_score = res[0][0].get("distance", 0)
    log.info(f"上下文检索到 {len(res[0])} 条结果，最高分: {top_score:.4f}")

    if top_score < settings.CONTEXT_SEARCH_THRESHOLD:
        log.info(f"最高分 {top_score:.4f} 低于阈值 {settings.CONTEXT_SEARCH_THRESHOLD}，丢弃上下文")
        return "没有找到相关的历史上下文信息。"

    context_pieces = [hit.get("context_text", "") for hit in res[0]]
    return "\n".join(context_pieces)


class SearchInput(BaseModel):
    query: str = Field(description="需要搜索的内容或者关键词")


@tool("my_search", args_schema=SearchInput, description="专门搜索互联网中的公开内容")
def my_search(query: str) -> str:
    """搜索互联网上所有的公开内容"""
    try:
        log.info(f"Tavily 搜索: {query}")
        response = tavily_client.search(query=query, max_results=3)
        results = response.get("results", [])
        log.info(f"Tavily 搜索完成，返回 {len(results)} 条结果")
        if results:
            return "\n\n".join([r["content"] for r in results])
        return "没有搜索到任何内容！"
    except Exception as e:
        log.error(f"Tavily 搜索失败: {e}")
        return "没有搜索到任何内容！"
