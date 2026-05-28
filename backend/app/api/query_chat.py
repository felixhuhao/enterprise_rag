"""Query chat API — POST /api/query/chat + SSE /api/query/chat/stream."""

import asyncio
import json
import logging
import time
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.deps import verify_token
from app.services.chat_history import load_history, save_message
from app.utils.sse import sse_event

logger = logging.getLogger(__name__)

router = APIRouter()


def _build_retrieved_chunks(search_results: list[dict]) -> str:
    """从最终检索结果构造 retrieved_chunks JSON。"""
    return json.dumps([
        {
            "chunk_id": r.get("chunk_id"),
            "rank": i + 1,
            "score": r.get("score", 0),
            "document_id": r.get("document_id", ""),
            "file_title": r.get("file_title", ""),
            "entity_name": r.get("entity_name", ""),
            "section_title": r.get("section_title", ""),
            "source_type": r.get("source_type", ""),
            "retrieval_path": r.get("retrieval_path", ""),
            "stage": "rerank",
        }
        for i, r in enumerate(search_results)
    ], ensure_ascii=False)


class QueryChatRequest(BaseModel):
    session_id: str = ""
    query: str = Field(..., max_length=4000)
    config: dict | None = None


def _build_config(req: QueryChatRequest):
    """从请求构建 QueryConfig。"""
    from app.rag.query.config import QueryConfig, get_default_query_config

    if not req.config:
        return get_default_query_config()
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


def _tick_ms(t0: float) -> int:
    """返回从 t0 到现在的毫秒数。"""
    return round((time.monotonic() - t0) * 1000)


async def _stream_generator(session_id: str, query: str, query_config):
    """两阶段 SSE 生成器。所有路径（成功/失败/中断）均落库 query_run_stats。"""
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
    from app.errors import classify_error
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
    from concurrent.futures import ThreadPoolExecutor
    import threading

    # RunnableConfig for nodes
    run_config = {"configurable": {"query_config": query_config}}

    # 外层变量初始化 — 所有路径都能安全取值
    state: dict = {}
    gen_trace: dict = {}
    cit_result: dict = {}
    status = "client_aborted"
    error_code = "CLIENT_ABORTED"

    # Phase 1: 搜索管线（同步，线程内执行）
    def run_search():
        trace: dict = {}
        t0 = time.monotonic()
        state = {"query": query}

        t = time.monotonic()
        state.update(entity_confirm_node(state, run_config))
        trace["entity_confirm_ms"] = _tick_ms(t)

        t = time.monotonic()
        state.update(rewrite_query_node(state, run_config))
        trace["rewrite_ms"] = _tick_ms(t)

        # 并行 search + hyde，wall time
        t = time.monotonic()
        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(search_node, state, run_config)
            f2 = pool.submit(hyde_search_node, state, run_config)
            state.update(f1.result())
            state.update(f2.result())
        trace["search_hyde_ms"] = _tick_ms(t)

        t = time.monotonic()
        state.update(rrf_fusion_node(state, run_config))
        trace["rrf_fusion_ms"] = _tick_ms(t)

        t = time.monotonic()
        state.update(table_expand_node(state, run_config))
        trace["table_expand_ms"] = _tick_ms(t)

        t = time.monotonic()
        state.update(rerank_node(state, run_config))
        trace["rerank_ms"] = _tick_ms(t)

        # Post-rerank fallback
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
                t_fb = time.monotonic()
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
                trace["post_rerank_fallback_ms"] = _tick_ms(t_fb)

        t = time.monotonic()
        state.update(build_prompt_node(state, run_config))
        trace["build_prompt_ms"] = _tick_ms(t)

        trace["retrieval_wall_ms"] = _tick_ms(t0)
        state["trace"] = trace
        return state

    # ── 所有 yield/await 都在 finally 保护内 ──
    try:
        yield sse_event({"type": "message_start"})

        # ── Phase 1: 搜索 ──
        try:
            state = await asyncio.to_thread(run_search)
        except Exception as exc:
            logger.exception("检索管线失败: %s", exc)
            status = "search_failed"
            error_code = classify_error(exc).value
            yield sse_event({"type": "error", "code": error_code, "message": str(exc)[:500]})
            yield sse_event({"type": "message_end"})
            return

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
            "entity_mode": state.get("entity_mode", "none"),
            "matched_entities": state.get("matched_entities", []),
            "per_entity_counts": state.get("per_entity_counts", {}),
        })

        # rerank debug（rerank 关闭时不发）
        rerank_debug = state.get("rerank_debug")
        if rerank_debug:
            yield sse_event({"type": "rerank", "results": rerank_debug})

        # Trace 第一阶段：检索耗时
        yield sse_event({"type": "trace", "trace": state.get("trace", {})})

        # ── Phase 2: LLM 流式生成（带对话历史） ──
        history = await load_history(session_id, limit=10)
        messages = [SystemMessage(content=state.get("context_text", ""))]
        for msg in history:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                messages.append(AIMessage(content=msg["content"]))
        messages.append(HumanMessage(content=state.get("query", "")))

        answer = ""
        llm_failed = False
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue[str | None | tuple] = asyncio.Queue()

        gen_t0 = time.monotonic()
        first_token_ts = None

        def _llm_producer():
            nonlocal answer, first_token_ts
            try:
                for chunk in _chat_llm.stream(messages):
                    if chunk.content:
                        if first_token_ts is None:
                            first_token_ts = time.monotonic()
                        answer += chunk.content
                        loop.call_soon_threadsafe(queue.put_nowait, chunk.content)
            except Exception as exc:
                code = classify_error(exc)
                loop.call_soon_threadsafe(
                    queue.put_nowait, ("error", code.value, str(exc)[:500])
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        t = threading.Thread(target=_llm_producer, daemon=True)
        t.start()

        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, tuple) and item[0] == "error":
                error_code = item[1]  # producer 已 classify
                yield sse_event({"type": "error", "code": error_code, "message": item[2]})
                llm_failed = True
                break
            yield sse_event({"type": "delta", "content": item})

        t.join()

        if llm_failed:
            status = "llm_failed"
            yield sse_event({"type": "message_end"})
            return

        # Trace 第二阶段：生成耗时
        gen_trace = {}
        if first_token_ts is not None:
            gen_trace["first_token_ms"] = round((first_token_ts - gen_t0) * 1000)
        gen_trace["generate_ms"] = round((time.monotonic() - gen_t0) * 1000)
        retrieval_wall = state.get("trace", {}).get("retrieval_wall_ms", 0)
        gen_trace["total_ms"] = retrieval_wall + gen_trace["generate_ms"]
        yield sse_event({"type": "trace", "trace": gen_trace})

        # ── Phase 3: 校验引用 ──
        state["answer"] = answer
        state["context_map"] = state.get("context_map", {})
        cit_result = validate_citations_node(state)
        yield sse_event({"type": "citations", "citations": cit_result.get("citations", [])})
        yield sse_event({"type": "message_end"})

        # 保存聊天历史
        try:
            await save_message(session_id, "user", query)
            await save_message(session_id, "assistant", answer, cit_result.get("citations"))
        except Exception:
            logger.warning("保存聊天历史失败", exc_info=True)

        # 成功
        status = "success"
        error_code = ""

    except asyncio.CancelledError:
        # 客户端中断 — status 已默认 client_aborted
        status = "client_aborted"
        error_code = "CLIENT_ABORTED"
        raise
    except Exception as exc:
        # Phase 2+ 非预期异常
        logger.exception("查询流非预期异常: %s", exc)
        status = "llm_failed"
        error_code = classify_error(exc).value
        yield sse_event({"type": "error", "code": error_code, "message": str(exc)[:500]})
        yield sse_event({"type": "message_end"})
        return
    finally:
        # 所有路径统一保存检索统计
        try:
            from app.services.query_stats_service import query_stats_service
            _rd = state.get("rerank_debug", [])
            rerank_avg = (
                sum(r["final_score"] for r in _rd) / len(_rd)
                if _rd else 0
            )
            rerank_top = _rd[0]["final_score"] if _rd else 0
            result_count = len(state.get("search_results", []))
            retrieved_chunks = _build_retrieved_chunks(state.get("search_results", []))
            save_task = asyncio.create_task(query_stats_service.save(
                session_id, query,
                state.get("search_mode", ""), state.get("search_mode_hyde", ""),
                result_count, rerank_avg, rerank_top,
                retrieval_wall_ms=state.get("trace", {}).get("retrieval_wall_ms", 0),
                first_token_ms=gen_trace.get("first_token_ms", 0),
                generate_ms=gen_trace.get("generate_ms", 0),
                total_ms=gen_trace.get("total_ms", 0),
                status=status,
                error_code=error_code,
                retrieved_chunks=retrieved_chunks,
            ))
            await asyncio.shield(save_task)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("保存检索统计失败", exc_info=True)
