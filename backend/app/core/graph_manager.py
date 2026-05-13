"""
LangGraph 图管理器模块

封装 LangGraph 编译图的操作，提供面向多会话的统一接口。
主要功能包括：
- 按会话（thread_id）隔离的流式执行和状态管理
- 支持人工审批中断（human-in-the-loop）和恢复执行
- 异步锁机制防止同一会话的并发冲突
"""

import asyncio
from typing import AsyncIterator

from graph.workflow import init_graph, update_state


class GraphManager:
    """
    LangGraph 操作封装类

    对 LangGraph 编译图进行封装，支持多会话并发执行。
    每个会话通过 thread_id 实现状态隔离，并使用 asyncio.Lock
    防止同一会话内出现并发写入冲突。
    """

    def __init__(self):
        """初始化图管理器，图实例在 init() 后才可用"""
        self.graph = None
        self._locks: dict[str, asyncio.Lock] = {}

    async def init(self):
        """异步初始化：创建 AsyncSqliteSaver 并编译图"""
        self.graph = await init_graph()

    def remove_lock(self, session_id: str):
        """
        删除指定会话的异步锁

        在会话被删除时调用，防止锁字典无限增长导致内存泄漏。

        参数:
            session_id: 会话唯一标识
        """
        self._locks.pop(session_id, None)

    def _get_lock(self, session_id: str) -> asyncio.Lock:
        """
        获取指定会话的异步锁

        若该会话尚无锁则自动创建，确保每个会话同一时刻只有一个流式操作在执行。

        参数:
            session_id: 会话唯一标识

        返回:
            该会话对应的 asyncio.Lock 实例
        """
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]

    def create_config(self, session_id: str, user_name: str = "ZS") -> dict:
        """
        创建会话配置（每个 thread_id 独立隔离）

        LangGraph 使用 configurable.thread_id 来区分不同会话的状态。
        同一个 thread_id 下，图的执行状态会被持久化保存。

        参数:
            session_id: 会话唯一标识，用作 LangGraph 的 thread_id
            user_name: 用户名，默认 "ZS"

        返回:
            LangGraph 所需的配置字典
        """
        return {
            "configurable": {
                "thread_id": session_id,
                "user_name": user_name,
            }
        }

    async def get_state(self, config: dict):
        """
        获取当前图状态快照

        参数:
            config: 会话配置字典

        返回:
            LangGraph 的 StateSnapshot 对象，包含当前消息列表和元数据
        """
        return await self.graph.aget_state(config)

    async def is_interrupted(self, config: dict) -> bool:
        """
        判断图是否处于中断状态（等待人工审批）

        当 state.next 非空时，表示图未执行完毕，处于中断等待状态。

        参数:
            config: 会话配置字典

        返回:
            True 表示图处于中断状态，False 表示已执行完毕
        """
        state = await self.graph.aget_state(config)
        return bool(state.next)

    async def set_human_answer(self, answer: str, config: dict):
        """
        设置人工审批回复并更新图状态

        通过 update_state 函数将审批结果（approve/rejected）
        写入图状态，以便后续从断点恢复执行。

        参数:
            answer: 审批结果，"approve" 或 "rejected"
            config: 会话配置字典
        """
        await update_state(answer, config)

    async def stream_chat(
        self, input_data: dict, config: dict
    ) -> AsyncIterator[dict]:
        """
        流式执行图，逐步 yield 每个 chunk

        以 stream_mode="values" 模式执行图，每次图节点执行完毕后
        都会 yield 当前完整的 state 快照。

        参数:
            input_data: 输入数据，包含 messages 列表
            config: 会话配置字典

        返回:
            异步迭代器，每次 yield 一个完整的 state 字典
        """
        async for chunk in self.graph.astream(input_data, config, stream_mode="values"):
            yield chunk

    async def resume_after_interrupt(self, config: dict) -> AsyncIterator[dict]:
        """
        从中断点恢复执行

        当人工审批完成后，传入 input_data=None 调用 astream，
        LangGraph 会自动从上次中断的节点继续执行。

        参数:
            config: 会话配置字典

        返回:
            异步迭代器，每次 yield 恢复后的 state 快照
        """
        import logging
        logger = logging.getLogger(__name__)
        async for chunk in self.graph.astream(None, config, stream_mode="values"):
            yield chunk
            # 检查图是否已到达终点，避免 astream 不自动终止的问题
            try:
                state = await self.graph.aget_state(config)
                if not state.next:
                    logger.info("resume_after_interrupt: 图已到达终点，主动结束流")
                    break
            except Exception:
                break


# 全局单例，整个应用共享同一个 GraphManager 实例
graph_manager = GraphManager()
