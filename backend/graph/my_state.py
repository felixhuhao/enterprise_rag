from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langgraph.graph.message import add_messages


class MultiModalRAGState(TypedDict, total=False):
    """多模态RAG状态"""

    messages: Annotated[list, add_messages]

    input_type: str                    # "has_text" | "only_image"
    context_retrieved: Optional[List[Dict[str, Any]]]
    image_retrieved: Optional[List[str]]

    need_retrieval: Optional[bool]
    evaluate_score: Optional[float]
    final_response: Optional[str]
    human_answer: Optional[str]

    input_image: Optional[str]         # base64编码
    input_text: Optional[str]
    user: str
    from_web_search: Optional[bool]    # 标记回复是否来自网络搜索
