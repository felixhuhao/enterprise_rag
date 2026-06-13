"""Query chat API — POST /api/query/chat + SSE /api/query/chat/stream."""

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.core.auth import CurrentUser, get_allowed_document_ids
from app.deps import verify_token
from app.services.chat_history import load_history, save_message
from app.services.query_observability import build_query_observability_payload
from app.rag.query.state import query_state_from_mapping, require_context_text, require_query
from app.utils.llm_usage import (
    extract_llm_token_usage,
    llm_model_name,
    merge_token_usage,
)
from app.utils.schema import ensure_dict
from app.utils.sse import sse_event
from app.utils.time import tick_ms

logger = logging.getLogger(__name__)

router = APIRouter()


def _build_retrieved_chunks(search_results: list[dict]) -> str:
    """从最终检索结果构造 retrieved_chunks JSON。"""
    return json.dumps([
        {
            "chunk_id": r.get("chunk_id"),
            "chunk_key": r.get("chunk_key", ""),
            "rank": i + 1,
            "score": r.get("score", 0),
            "document_id": r.get("document_id", ""),
            "file_title": r.get("file_title", ""),
            "entity_name": r.get("entity_name", ""),
            "section_title": r.get("section_title", ""),
            "page": r.get("page"),
            "table_id": r.get("table_id", ""),
            "source_type": r.get("source_type", ""),
            "keywords": r.get("keywords", []),
            "structured_tags": r.get("structured_tags", []),
            "retrieval_path": _retrieval_path(r),
            "context_expanded_chunk_ids": r.get("context_expanded_chunk_ids", []),
            "context_expand_parts": r.get("context_expand_parts", []),
            "stage": "rerank",
            "content_preview": _content_preview(r),
        }
        for i, r in enumerate(search_results)
    ], ensure_ascii=False)


def _content_preview(row: dict, limit: int = 240) -> str:
    text = str(row.get("content") or "")
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _retrieval_path(row: dict) -> str:
    path = row.get("retrieval_path")
    if path:
        return path
    paths = row.get("retrieval_paths")
    if isinstance(paths, list) and paths:
        return " + ".join(str(p) for p in paths if p)
    if row.get("source_type", "").startswith("table_"):
        return "table"
    return "primary"


def _llm_model_name(llm: Any) -> str:
    return llm_model_name(llm)


def _extract_llm_chunk_token_usage(chunk: Any, model_name: str = "") -> dict:
    """Extract token usage from LangChain chat chunks when providers expose it."""
    return extract_llm_token_usage(chunk, model_name)


def _merge_token_usage(existing: dict, update: dict) -> dict:
    return merge_token_usage(existing, update)


def _query_status_from_error_code(code: str) -> str:
    if code == "LLM_ERROR":
        return "llm_failed"
    if code in {"MILVUS_ERROR", "EMBEDDING_ERROR", "NO_CONTEXT_FOUND"}:
        return "search_failed"
    return "query_failed"


class QueryChatRequest(BaseModel):
    session_id: str = ""
    query: str = Field(..., max_length=4000)
    config: dict | None = None
    is_eval: bool = False


def _build_config(req: QueryChatRequest):
    """从请求构建 QueryConfig。过滤非法 key，跳过类型不匹配的值。"""
    from app.rag.query.config import QueryConfig, _cast_field, get_default_query_config

    if not req.config:
        return get_default_query_config()
    valid = {}
    for k, v in req.config.items():
        if not hasattr(QueryConfig, k):
            continue
        field = QueryConfig.__dataclass_fields__[k]
        casted = _cast_field(k, str(v), field.type)
        if casted is not None:
            valid[k] = casted
    return QueryConfig(**valid)


@router.post("/query/chat")
async def query_chat(req: QueryChatRequest, current_user: CurrentUser = Depends(verify_token)):
    """非流式查询，返回 answer + citations。"""
    from app.rag.query.graph import run_query_graph
    from app.errors import classify_error
    from app.rag.query.fallback import fallback_was_used, state_fallback_info
    from app.services.query_stats_service import query_stats_service

    t0 = time.monotonic()
    session_id = req.session_id or str(uuid.uuid4())
    is_eval = bool(req.is_eval and current_user.role == "admin")
    query_config = _build_config(req)
    allowed_ids = await get_allowed_document_ids(current_user)

    try:
        result = await asyncio.to_thread(run_query_graph, req.query, query_config,
                                         {"allowed_document_ids": allowed_ids})
    except Exception as exc:
        logger.exception("非流式查询失败: %s", exc)
        code = classify_error(exc).value
        status = _query_status_from_error_code(code)
        if not is_eval:
            try:
                total_ms = tick_ms(t0)
                observability = build_query_observability_payload(
                    endpoint="query_chat",
                    status=status,
                    error_code=code,
                    trace={"total_ms": total_ms},
                    query_config=query_config,
                )
                await query_stats_service.save(
                    session_id,
                    req.query,
                    "",
                    "",
                    0,
                    0,
                    0,
                    total_ms=total_ms,
                    status=status,
                    error_code=code,
                    user_id=current_user.user_id,
                    retrieval_flavor=query_config.retrieval_flavor,
                    strict_evidence=query_config.strict_evidence,
                    observability=observability,
                )
            except Exception:
                logger.warning("保存非流式失败统计失败", exc_info=True)
        raise HTTPException(status_code=500, detail={"code": code, "message": str(exc)[:500]}) from exc

    obs_state = ensure_dict(result.get("_observability_state"))
    obs_trace = ensure_dict(result.get("_observability_trace"))
    token_usage = ensure_dict(result.get("_token_usage"))

    # 保存聊天历史
    if not is_eval:
        try:
            await save_message(session_id, "user", req.query, user_id=current_user.user_id)
            await save_message(session_id, "assistant", result.get("answer", ""), result.get("citations"), user_id=current_user.user_id)
        except Exception:
            logger.warning("保存聊天历史失败", exc_info=True)
        try:
            fallback_info = result.get("fallback_info")
            if not isinstance(fallback_info, dict):
                fallback_info = state_fallback_info(query_state_from_mapping(query=req.query))
            fallback_state = {**obs_state, "fallback_info": fallback_info}
            fallback_used_flag = fallback_was_used(fallback_state)
            _rd = obs_state.get("rerank_debug", [])
            rerank_avg = (
                sum(r["final_score"] for r in _rd) / len(_rd)
                if _rd else 0
            )
            rerank_top = _rd[0]["final_score"] if _rd else 0
            search_results = obs_state.get("search_results", [])
            groundedness = ensure_dict(result.get("groundedness"))
            observability = build_query_observability_payload(
                endpoint="query_chat",
                status="success",
                error_code="",
                state=obs_state,
                trace=obs_trace,
                query_config=query_config,
                citations=result.get("citations", []),
                fallback_info=fallback_info,
                token_usage=token_usage,
            )
            await query_stats_service.save(
                session_id,
                req.query,
                result.get("search_mode", ""),
                result.get("search_mode_hyde", ""),
                int(result.get("results_count", 0) or 0),
                rerank_avg,
                rerank_top,
                retrieval_wall_ms=obs_trace.get("retrieval_wall_ms", 0),
                generate_ms=obs_trace.get("generate_ms", 0),
                total_ms=obs_trace.get("total_ms", tick_ms(t0)),
                status="success",
                retrieved_chunks=_build_retrieved_chunks(search_results),
                groundedness_score=groundedness.get("groundedness_score"),
                user_id=current_user.user_id,
                retrieval_flavor=result.get("retrieval_flavor", query_config.retrieval_flavor),
                strict_evidence=bool(result.get("strict_evidence", query_config.strict_evidence)),
                citations=result.get("citations", []),
                fallback_used=fallback_used_flag,
                observability=observability,
            )
        except Exception:
            logger.warning("保存非流式检索统计失败", exc_info=True)

    result.pop("_observability_state", None)
    result.pop("_observability_trace", None)
    result.pop("_token_usage", None)
    result["session_id"] = session_id
    return result


@router.post("/query/chat/stream")
async def query_chat_stream(req: QueryChatRequest, current_user: CurrentUser = Depends(verify_token)):
    """SSE 流式查询。两阶段：graph 跑搜索 → LLM 流式生成。"""
    session_id = req.session_id or str(uuid.uuid4())
    is_eval = bool(req.is_eval and current_user.role == "admin")
    query_config = _build_config(req)
    allowed_ids = await get_allowed_document_ids(current_user)
    return EventSourceResponse(
        _stream_generator(session_id, req.query, query_config, allowed_ids, current_user.user_id, is_eval),
        media_type="text/event-stream",
    )


async def _stream_generator(
    session_id: str,
    query: str,
    query_config,
    allowed_ids,
    user_id: str = "",
    is_eval: bool = False,
):
    """两阶段 SSE 生成器。所有路径（成功/失败/中断）均落库 query_run_stats。"""
    from app.rag.query.build_prompt import build_prompt_node
    from app.rag.query.fallback import fallback_was_used, state_fallback_info
    from app.rag.query.generate import _chat_llm
    from app.rag.query.search_pipeline import run_search_pipeline
    from app.rag.query.validate_citations import validate_citations_node
    from app.errors import classify_error
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
    import threading

    # RunnableConfig for nodes
    run_config = {"configurable": {
        "query_config": query_config,
        "allowed_document_ids": allowed_ids,
        "current_user_id": user_id,
        "is_eval": is_eval,
    }}

    # 外层变量初始化 — 所有路径都能安全取值
    state = query_state_from_mapping(query=query)
    gen_trace: dict = {}
    cit_result: dict = {}
    gr_result: dict = {}
    token_usage: dict = {"model": _llm_model_name(_chat_llm)}
    status = "client_aborted"
    error_code = "CLIENT_ABORTED"

    # Phase 1: 搜索管线（同步，线程内执行）
    def run_search():
        trace: dict = {}
        search_state = run_search_pipeline(query, run_config, trace=trace)

        t = time.monotonic()
        search_state.update(build_prompt_node(search_state, run_config))
        trace["build_prompt_ms"] = tick_ms(t)
        trace["retrieval_wall_ms"] = trace.get("retrieval_wall_ms", 0) + trace["build_prompt_ms"]
        search_state["trace"] = trace
        return search_state

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
            "alias_trace": state.get("alias_trace", []),
            "expanded_queries": state.get("expanded_queries", []),
            "per_query_counts": state.get("per_query_counts", {}),
            "query_expansion_trace": state.get("query_expansion_trace", []),
            "hop_plan": state.get("hop_plan", "direct"),
            "hop_trace": state.get("hop_trace", []),
            "retrieval_flavor": state.get("query_plan", {}).get("retrieval_flavor", "balanced"),
            "strict_evidence": state.get("query_plan", {}).get("strict_evidence", False),
            "query_plan": state.get("query_plan", {}),
            "fallback_info": state.get("fallback_info", {}),
        })

        # rerank debug（rerank 关闭时不发）
        rerank_debug = state.get("rerank_debug")
        if rerank_debug:
            yield sse_event({"type": "rerank", "results": rerank_debug})

        # Trace 第一阶段：检索耗时
        yield sse_event({"type": "trace", "trace": state.get("trace", {})})

        # ── Phase 2: LLM 流式生成（带对话历史） ──
        history = [] if is_eval else await load_history(session_id, user_id=user_id, limit=10)
        messages = [SystemMessage(content=require_context_text(state))]
        for msg in history:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                messages.append(AIMessage(content=msg["content"]))
        messages.append(HumanMessage(content=require_query(state)))

        answer = ""
        llm_failed = False
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue[str | None | tuple] = asyncio.Queue()

        gen_t0 = time.monotonic()
        first_token_ts = None

        def _llm_producer():
            nonlocal answer, first_token_ts, token_usage
            try:
                for chunk in _chat_llm.stream(messages):
                    token_usage = _merge_token_usage(
                        token_usage,
                        _extract_llm_chunk_token_usage(chunk, token_usage.get("model", "")),
                    )
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
        gen_trace["generate_ms"] = tick_ms(gen_t0)
        retrieval_wall = state.get("trace", {}).get("retrieval_wall_ms", 0)
        gen_trace["total_ms"] = retrieval_wall + gen_trace["generate_ms"]
        yield sse_event({"type": "trace", "trace": gen_trace})

        # ── Phase 3: 校验引用 ──
        state["answer"] = answer
        state["context_map"] = state.get("context_map", {})
        cit_result = validate_citations_node(state)
        state.update(cit_result)
        yield sse_event({"type": "citations", "citations": cit_result.get("citations", [])})

        # ── Phase 4: Groundedness check（仅 enabled 时发送 SSE 事件）──
        try:
            from app.rag.query.groundedness import groundedness_check_node
            gr_result = await asyncio.to_thread(groundedness_check_node, state, run_config)
            gr_data = gr_result.get("groundedness", {})
            if gr_data.get("status") != "skipped":
                yield sse_event({"type": "groundedness", **gr_data})
        except Exception:
            logger.warning("Groundedness check failed", exc_info=True)
            yield sse_event({"type": "groundedness", "enabled": True, "status": "unavailable",
                             "groundedness_score": None, "claims": [], "warning": "依据覆盖检查失败"})

        yield sse_event({"type": "message_end"})

        if not is_eval:
            try:
                await save_message(session_id, "user", query, user_id=user_id)
                await save_message(session_id, "assistant", answer, cit_result.get("citations"), user_id=user_id)
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
        if not is_eval:
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
                query_plan = state.get("query_plan", {}) or {}
                fallback_info = state_fallback_info(state)
                fallback_used_flag = fallback_was_used(state)
                observability = build_query_observability_payload(
                    endpoint="query_chat_stream",
                    status=status,
                    error_code=error_code,
                    state=state,
                    trace=state.get("trace", {}),
                    gen_trace=gen_trace,
                    query_config=query_config,
                    citations=cit_result.get("citations", []),
                    fallback_info=fallback_info,
                    token_usage=token_usage,
                )
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
                    groundedness_score=gr_result.get("groundedness", {}).get("groundedness_score"),
                    user_id=user_id,
                    retrieval_flavor=query_plan.get("retrieval_flavor", "balanced"),
                    strict_evidence=bool(query_plan.get("strict_evidence", False)),
                    citations=cit_result.get("citations", []),
                    fallback_used=fallback_used_flag,
                    observability=observability,
                ))
                await asyncio.shield(save_task)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("保存检索统计失败", exc_info=True)
