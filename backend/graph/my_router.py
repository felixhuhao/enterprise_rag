from langgraph.constants import END

from app.core.runtime_settings import runtime_settings
from graph.my_state import MultiModalRAGState
from utils.log_utils import log


def route_only_image(state: MultiModalRAGState):
    """
    动态路由函数，如果用户仅仅输入图片，则进入LLM节点，否则进入知识库检索节点
    """

    if state.get('input_type') == 'only_image':
        return "retriever_node"
    return 'first_chatbot'


def route_llm_or_retriever(state: MultiModalRAGState):
    """
    动态路由函数，如果上下文检索到结果，则进入LLM节点，否则进入知识库检索节点
    """
    if messages := state.get("messages", []):
        tool_message = messages[-1]
    else:
        raise ValueError("No message found in input")

    if not tool_message.content or tool_message.content == "没有找到相关的历史上下文信息。":
        return "retriever_node"
    return 'second_chatbot'


def route_evaluate_node(state: MultiModalRAGState):
    """
    动态路由函数，如果用户仅仅输入图片，则不进行评估（目前RAGAS还不支持多模态评估），其他情况下进入评估节点
    """

    if state.get('input_type') == 'only_image':
        return END
    return 'evaluate_node'


def route_human_node(state: MultiModalRAGState):
    """
    动态路由函数，根据评估分数决定：
    - >= 0.8：自动 approve，直接结束
    - 0.6 ~ 0.8：需要人工审核
    - < 0.6：自动 reject，进入网络搜索
    """
    score = state.get('evaluate_score', 0)
    threshold_high = runtime_settings.get_cached_float("evaluate_threshold_high")
    threshold_low = runtime_settings.get_cached_float("evaluate_threshold_low")
    if score >= threshold_high:
        log.info(f"route_human_node: score={score:.4f} >= {threshold_high} → END")
        return END
    if score < threshold_low:
        log.info(f"route_human_node: score={score:.4f} < {threshold_low} → auto_reject")
        return 'auto_reject'
    log.info(f"route_human_node: score={score:.4f} → human_approval")
    return 'human_approval'


def route_human_approval_node(state: MultiModalRAGState):
    """
    动态路由函数，如果用户输入的是：approve 则结束，否则进入网络搜索
    """
    answer = state.get('human_answer', '')
    if answer == 'approve':
        log.info(f"route_human_approval_node: human_answer={answer} → END")
        return END
    log.info(f"route_human_approval_node: human_answer={answer} → fourth_chatbot")
    return 'fourth_chatbot'

