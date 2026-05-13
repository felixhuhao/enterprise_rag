# ruff: noqa: E402
import asyncio
import sys
import warnings
from typing import List, Dict, Optional

warnings.filterwarnings("ignore", category=DeprecationWarning, module="ragas")

import instructor
from openai import AsyncOpenAI
from ragas.llms import InstructorLLM
from ragas.embeddings import OpenAIEmbeddings as RagasOpenAIEmbeddings
from ragas.metrics.collections import (
    ContextPrecisionWithReference,
    ContextPrecisionWithoutReference,
    AnswerRelevancy,
    ContextRelevance,
)

from milvus_db.db_retriever import MilvusRetriever
from my_llm import multiModal_llm
from app.config import settings
from utils.log_utils import log

_eval_client = instructor.from_openai(
    AsyncOpenAI(api_key=settings.DASHSCOPE_API_KEY, base_url=settings.DASHSCOPE_BASE_URL),
    mode=instructor.Mode.JSON,
)
evaluator_llm = InstructorLLM(
    client=_eval_client,
    model=settings.EVAL_MODEL,
    provider="openai",
)
evaluator_embeddings = RagasOpenAIEmbeddings(
    client=AsyncOpenAI(api_key=settings.DASHSCOPE_API_KEY, base_url=settings.DASHSCOPE_BASE_URL),
    model=settings.EMBEDDING_MODEL,
)


def generate_answer(question: str, contexts: List[Dict]) -> str:
    """
    基于检索到的上下文，调用 LLM 生成答案

    Args:
        question: 用户问题
        contexts: MilvusRetriever.retrieve() 返回的结果列表

    Returns:
        LLM 生成的答案
    """
    context_str = "\n\n".join(
        [f"上下文 {i + 1}: {ctx['text']}" for i, ctx in enumerate(contexts)]
    )

    prompt = f"""你是一个AI助手，需要根据提供的上下文回答用户的问题。请确保你的回答基于提供的上下文，不要添加额外信息。

用户问题: {question}

检索到的上下文:
{context_str}

请基于以上上下文回答用户问题。"""

    llm = multiModal_llm
    response = llm.invoke(prompt)
    return response.content


class RAGEvaluator:
    """RAG 系统评估器，基于 ragas 0.4+ collections API"""

    def __init__(self):
        self.evaluator_llm = evaluator_llm
        self.evaluator_embeddings = evaluator_embeddings

    async def evaluate_context(self, question: str, contexts: List[str]) -> float:
        """
        上下文相关性评估：检索到的上下文是否与用户问题相关

        Returns:
            0~1 分数
        """
        scorer = ContextRelevance(llm=self.evaluator_llm)
        result = await scorer.ascore(user_input=question, retrieved_contexts=contexts)
        return result.value

    async def evaluate_answer(self, question: str, response: str) -> float:
        """
        答案相关性评估：生成的答案是否与用户问题相关

        Returns:
            0~1 分数
        """
        scorer = AnswerRelevancy(llm=self.evaluator_llm, embeddings=self.evaluator_embeddings)
        result = await scorer.ascore(user_input=question, response=response)
        return result.value

    async def evaluate_context_precision(
        self,
        question: str,
        contexts: List[str],
        response: str,
        reference: Optional[str] = None,
    ) -> float:
        """
        上下文精确度评估

        Args:
            reference: 可选的参考答案（提供时使用 WithReference 模式）

        Returns:
            0~1 分数
        """
        if reference:
            scorer = ContextPrecisionWithReference(llm=self.evaluator_llm)
            result = await scorer.ascore(
                user_input=question,
                reference=reference,
                retrieved_contexts=contexts,
            )
        else:
            scorer = ContextPrecisionWithoutReference(llm=self.evaluator_llm)
            result = await scorer.ascore(
                user_input=question,
                response=response,
                retrieved_contexts=contexts,
            )
        return result.value

    async def evaluate_all(
        self,
        question: str,
        contexts: List[Dict],
        response: str,
        reference: Optional[str] = None,
    ) -> Dict[str, float]:
        """
        运行所有评估指标

        Returns:
            {"context_relevance": ..., "answer_relevancy": ..., "context_precision": ...}
        """
        context_texts = [ctx["text"] for ctx in contexts]

        scores = {}

        log.info("评估上下文相关性...")
        scores["context_relevance"] = await self.evaluate_context(question, context_texts)

        log.info("评估答案相关性...")
        scores["answer_relevancy"] = await self.evaluate_answer(question, response)

        log.info("评估上下文精确度...")
        scores["context_precision"] = await self.evaluate_context_precision(
            question, context_texts, response, reference
        )

        return scores


async def main():
    question = "收盘集合竞价机制是什么？" if len(sys.argv) < 2 else sys.argv[1]

    # 1. 检索上下文
    retriever = MilvusRetriever(top_k=3)
    contexts = retriever.retrieve(question)

    print(f"问题: {question}")
    print(f"检索到 {len(contexts)} 条上下文\n")

    for i, ctx in enumerate(contexts):
        print(f"  [{i + 1}] score={ctx['score']:.4f}, title={ctx['title']}")
        print(f"      {ctx['text'][:60]}...")
    print()

    # 2. 生成答案
    answer = generate_answer(question, contexts)
    print(f"生成的答案:\n{answer}\n")

    # 3. 评估
    evaluator = RAGEvaluator()
    scores = await evaluator.evaluate_all(question, contexts, answer)

    print("=" * 40)
    print("评估结果:")
    for metric, score in scores.items():
        print(f"  {metric}: {score:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
