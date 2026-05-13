"""
SSE 事件格式化工具

将数据字典序列化为 JSON 字符串，供 sse-starlette 的 EventSourceResponse 使用。
sse-starlette 会自动添加 "data: " 前缀和 "\n\n" 后缀，这里只需返回纯 JSON。
"""

import json


def sse_event(data: dict) -> str:
    """
    格式化单个 SSE 事件数据

    参数:
        data: 事件数据字典，必须包含 "type" 字段

    返回:
        JSON 字符串，由 sse-starlette 自动包装为 SSE 协议格式
    """
    return json.dumps(data, ensure_ascii=False)
