from langchain_core.messages import AIMessage

from evaluate.rag_eval import RAGEvaluator
from graph.my_state import MultiModalRAGState
from utils.log_utils import log

rag_evaluator = RAGEvaluator()


async def evaluate_answer(state: MultiModalRAGState):
    """评估 AI 回复与用户问题的相关性（AnswerRelevancy）"""
    input_text = state.get('input_text')

    # 从 messages 中提取最后一条 AI 回复（非工具调用）
    answer = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, AIMessage) and not msg.tool_calls:
            answer = msg.content
            break

    if not answer:
        log.info("RAG Evaluation: 未找到 AI 回复，评分 0.0")
        return {"evaluate_score": 0.0}

    score = await rag_evaluator.evaluate_answer(input_text, answer)
    log.info(f"RAG AnswerRelevancy Score: {score}")
    return {"evaluate_score": float(score)}
