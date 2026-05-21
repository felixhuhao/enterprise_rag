"""Query chat API — POST /api/query/chat + SSE /api/query/chat/stream."""

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.deps import verify_token
from app.services.chat_history import load_history, save_message
from app.utils.sse import sse_event

logger = logging.getLogger(__name__)

router = APIRouter()


class QueryChatRequest(BaseModel):
    session_id: str = ""
    query: str
    config: dict | None = None


def _build_config(req: QueryChatRequest):
    """从请求构建 QueryConfig。"""
    from app.rag.query.config import QueryConfig

    if not req.config:
        return QueryConfig()
    valid = {k: v for k, v in req.config.items() if hasattr(QueryConfig, k)}
    return QueryConfig(**valid)


@router.post("/query/chat")
async def query_chat(req: QueryChatRequest, _: None = Depends(verify_token)):
    """非流式查询，返回 answer + citations。"""
    from app.rag.query.graph import run_query_graph

    session_id = req.session_id or str(uuid.uuid4())
    query_config = _build_config(req)

    result = await asyncio.to_thread(run_query_graph, req.query, query_config)

    # 保存聊天历史
    try:
        await save_message(session_id, "user", req.query)
        await save_message(session_id, "assistant", result.get("answer", ""), result.get("citations"))
    except Exception:
        logger.warning("保存聊天历史失败", exc_info=True)

    result["session_id"] = session_id
    return result


@router.post("/query/chat/stream")
async def query_chat_stream(req: QueryChatRequest, _: None = Depends(verify_token)):
    """SSE 流式查询。两阶段：graph 跑搜索 → LLM 流式生成。"""
    session_id = req.session_id or str(uuid.uuid4())
    query_config = _build_config(req)
    return EventSourceResponse(
        _stream_generator(session_id, req.query, query_config),
        media_type="text/event-stream",
    )


async def _stream_generator(session_id: str, query: str, query_config):
    """两阶段 SSE 生成器。"""
    from app.rag.query.entity_confirm import entity_confirm_node
    from app.rag.query.rewrite_query import rewrite_query_node
    from app.rag.query.search import search_node
    from app.rag.query.hyde_search import hyde_search_node
    from app.rag.query.rrf_fusion import rrf_fusion_node
    from app.rag.query.table_expand import table_expand_node
    from app.rag.query.rerank import rerank_node
    from app.rag.query.build_prompt import build_prompt_node
    from app.rag.query.generate import _chat_llm
    from app.rag.query.validate_citations import validate_citations_node
    from langchain_core.messages import HumanMessage, SystemMessage
    from concurrent.futures import ThreadPoolExecutor

    # RunnableConfig for nodes
    run_config = {"configurable": {"query_config": query_config}}

    yield sse_event({"type": "message_start"})

    # Phase 1: 搜索管线（同步，线程内执行）
    def run_search():
        state = {"query": query}
        state.update(entity_confirm_node(state, run_config))
        state.update(rewrite_query_node(state, run_config))
        # 并行 search + hyde
        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(search_node, state, run_config)
            f2 = pool.submit(hyde_search_node, state, run_config)
            state.update(f1.result())
            state.update(f2.result())
        state.update(rrf_fusion_node(state, run_config))
        state.update(table_expand_node(state, run_config))
        state.update(rerank_node(state, run_config))

        # Post-rerank fallback: 如果 rerank 最高分低于阈值且有 entity filter，且搜索阶段没 fallback 过，去掉 filter 重搜
        entity_filter = state.get("entity_filter")
        already_fell_back = (
            "fallback" in state.get("search_mode", "")
            or "fallback" in state.get("search_mode_hyde", "")
        )
        results = state.get("search_results", [])
        if entity_filter and not already_fell_back and results:
            top_score = results[0].get("score", 0)
            if top_score < query_config.entity_filter_rerank_min_score:
                logger.info(
                    "Post-rerank fallback: top_score=%.3f < %.3f, retrying unfiltered",
                    top_score, query_config.entity_filter_rerank_min_score,
                )
                state["entity_filter"] = ""
                with ThreadPoolExecutor(max_workers=2) as pool:
                    f1 = pool.submit(search_node, state, run_config)
                    f2 = pool.submit(hyde_search_node, state, run_config)
                    state.update(f1.result())
                    state.update(f2.result())
                state.update(rrf_fusion_node(state, run_config))
                state.update(table_expand_node(state, run_config))
                state.update(rerank_node(state, run_config))
                state["search_mode"] = state.get("search_mode", "") + "_post_rerank_fallback"

        state.update(build_prompt_node(state, run_config))
        return state

    state = await asyncio.to_thread(run_search)

    count = len(state.get("search_results", []))
    entity = state.get("confirmed_entity", "")
    rewritten = state.get("rewritten_query", "")
    yield sse_event({
        "type": "retrieval_step",
        "results_count": count,
        "entity": entity,
        "rewritten_query": rewritten,
        "search_mode": state.get("search_mode", ""),
        "search_mode_hyde": state.get("search_mode_hyde", ""),
    })

    # rerank debug（rerank 关闭时不发）
    rerank_debug = state.get("rerank_debug")
    if rerank_debug:
        yield sse_event({"type": "rerank", "results": rerank_debug})

    # Phase 2: LLM 流式生成（带对话历史）
    from langchain_core.messages import AIMessage

    history = await load_history(session_id, limit=10)
    messages = [SystemMessage(content=state.get("context_text", ""))]
    for msg in history:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            messages.append(AIMessage(content=msg["content"]))
    messages.append(HumanMessage(content=state.get("query", "")))

    answer = ""
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def _llm_producer():
        nonlocal answer
        try:
            for chunk in _chat_llm.stream(messages):
                if chunk.content:
                    answer += chunk.content
                    loop.call_soon_threadsafe(queue.put_nowait, chunk.content)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    import threading
    t = threading.Thread(target=_llm_producer, daemon=True)
    t.start()

    while True:
        token = await queue.get()
        if token is None:
            break
        yield sse_event({"type": "delta", "content": token})

    t.join()

    # Phase 3: 校验引用
    state["answer"] = answer
    state["context_map"] = state.get("context_map", {})
    cit_result = validate_citations_node(state)
    yield sse_event({"type": "citations", "citations": cit_result.get("citations", [])})
    yield sse_event({"type": "message_end"})

    # 保存历史
    try:
        await save_message(session_id, "user", query)
        await save_message(session_id, "assistant", answer, cit_result.get("citations"))
    except Exception:
        logger.warning("保存聊天历史失败", exc_info=True)


@router.get("/query/chat/history")
async def query_chat_history(
    session_id: str,
    _: None = Depends(verify_token),
):
    """获取指定 session 的聊天历史。"""
    messages = await load_history(session_id)
    return {"session_id": session_id, "messages": messages}
