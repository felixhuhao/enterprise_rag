"""
聊天核心服务模块

实现 SSE 流式聊天功能。将用户消息发送到 LangGraph 图并流式获取 AI 回复。
图片处理和 SSE 格式化已提取到 app.utils 公共模块。
"""

import asyncio
import logging

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.core.graph_manager import graph_manager
from app.utils.sse import sse_event
from app.utils.image import local_images_to_data_uri
from app.config import settings

logger = logging.getLogger(__name__)


async def _save_evaluate_if_present(session_id: str, input_text: str | None, state):
    """如果图状态中存在 evaluate_score，则保存评估记录到数据库"""
    score = state.values.get("evaluate_score")
    if score is not None:
        try:
            from app.services.evaluate_service import evaluate_service
            await evaluate_service.save_record(
                session_id=session_id,
                input_text=input_text or "",
                score=float(score),
                from_web_search=bool(state.values.get("from_web_search")),
            )
        except Exception as e:
            logger.warning("保存评估记录失败: %s", e)


async def chat_stream_generator(
    session_id: str,
    text: str | None,
    image_base64: str | None,
):
    """
    核心 SSE 流式生成器：发送消息并流式返回 AI 回复
    """
    config = graph_manager.create_config(session_id)
    lock = graph_manager._get_lock(session_id)

    async with lock:
        # 构建多模态用户消息内容
        user_content = []
        if text:
            user_content.append({"type": "text", "text": text})
        if image_base64:
            user_content.append({"type": "image_url", "image_url": {"url": image_base64}})

        if not user_content:
            yield sse_event({"type": "error", "data": {"message": "消息不能为空"}})
            return

        input_data = {"messages": [HumanMessage(content=user_content)]}
        current_state = await graph_manager.get_state(config)
        last_msg_count = len(current_state.values.get("messages", []))

        yield sse_event({"type": "message_start"})

        async for chunk in graph_manager.stream_chat(input_data, config):
            messages = chunk.get("messages", [])
            if len(messages) > last_msg_count:
                for i in range(last_msg_count, len(messages)):
                    msg = messages[i]

                    if isinstance(msg, ToolMessage) and msg.name:
                        content_preview = msg.content[:settings.TOOL_CONTENT_PREVIEW_LENGTH]
                        yield sse_event({
                            "type": "tool_call",
                            "data": {
                                "tool_name": msg.name,
                                "content": content_preview,
                            },
                        })
                    elif isinstance(msg, AIMessage) and not msg.tool_calls:
                        rendered = await local_images_to_data_uri(msg.content)
                        yield sse_event({
                            "type": "assistant_chunk",
                            "data": {"content": rendered},
                        })

                last_msg_count = len(messages)

        # 流式执行完毕
        final_state = await graph_manager.get_state(config)
        if final_state.next:
            score = final_state.values.get("evaluate_score", 0)
            await _save_evaluate_if_present(session_id, text, final_state)
            yield sse_event({
                "type": "interrupt",
                "data": {
                    "reason": "needs_approval",
                    "score": score,
                },
            })
        else:
            await _save_evaluate_if_present(session_id, text, final_state)
            if final_state.values.get("from_web_search"):
                _try_save_context(final_state)

            yield sse_event({
                "type": "message_end",
                "data": {"from_web_search": final_state.values.get("from_web_search", False)},
            })


def _try_save_context(state):
    """尝试将网络搜索结果写入 Milvus 向量库（非阻塞）"""
    try:
        messages = state.values.get("messages", [])
        if not messages or not isinstance(messages[-1], AIMessage):
            return
        text = messages[-1].content
        if isinstance(text, list):
            return

        from graph.save_context import get_milvus_writer

        task = asyncio.create_task(
            get_milvus_writer().async_insert(
                context_text=text,
                user=state.values.get("user", settings.DEFAULT_USER_NAME),
                message_type="AIMessage",
            )
        )

        def _on_done(t):
            if t.exception():
                logger.error("Milvus 写入失败: %s", t.exception())

        task.add_done_callback(_on_done)
    except Exception as e:
        logger.warning("Milvus 上下文保存失败: %s", e)
