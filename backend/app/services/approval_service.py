"""
审批流式服务模块

处理人工审批（human-in-the-loop）场景的 SSE 流式响应。
"""

import logging

from langchain_core.messages import AIMessage

from app.core.graph_manager import graph_manager
from app.utils.sse import sse_event
from app.utils.image import local_images_to_data_uri

logger = logging.getLogger(__name__)


async def approval_stream_generator(session_id: str, action: str):
    """
    审批流式生成器：approve 或 rejected 后恢复工作流
    """
    config = graph_manager.create_config(session_id)
    lock = graph_manager._get_lock(session_id)

    async with lock:
        if not await graph_manager.is_interrupted(config):
            yield sse_event({"type": "error", "data": {"message": "当前会话不在审批状态"}})
            return

        await graph_manager.set_human_answer(action, config)

        # 记录恢复前的消息数量，避免重复发送中断前的消息
        state_before = await graph_manager.get_state(config)
        last_msg_count = len(state_before.values.get("messages", []))
        logger.info(f"审批恢复: action={action}, 恢复前消息数={last_msg_count}")

        yield sse_event({"type": "message_start"})

        chunk_count = 0
        async for chunk in graph_manager.resume_after_interrupt(config):
            chunk_count += 1
            messages = chunk.get("messages", [])
            logger.info(f"审批 chunk #{chunk_count}: 消息数={len(messages)}, last_msg_count={last_msg_count}")
            if len(messages) > last_msg_count:
                for i in range(last_msg_count, len(messages)):
                    msg = messages[i]
                    if isinstance(msg, AIMessage) and not msg.tool_calls:
                        rendered = await local_images_to_data_uri(msg.content)
                        yield sse_event({
                            "type": "assistant_chunk",
                            "data": {"content": rendered},
                        })
                last_msg_count = len(messages)

        logger.info(f"审批流结束: 共 {chunk_count} 个 chunk, 发送 message_end")
        yield sse_event({"type": "message_end", "data": {}})
