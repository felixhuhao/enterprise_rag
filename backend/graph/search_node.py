import asyncio

from langchain_core.messages import ToolMessage

from graph.my_state import MultiModalRAGState
from milvus_db.db_retriever import MilvusRetriever
from utils.embedding_utils import VLEmbeddingClient, embed_for_knowledge_base
from utils.log_utils import log

m_re = MilvusRetriever(top_k=3)
vl_client = VLEmbeddingClient()


#  自定义是为了替代：由LangGraph框架自带的ToolNode（有大模型动态传参 来调用工具）
class SearchContextToolNode:
    """自定义类，来执行搜索上下文工具"""

    def __init__(self, tools: list) -> None:
        self.tools_by_name = {tool.name: tool for tool in tools}

    async def __call__(self, inputs: dict):
        if messages := inputs.get("messages", []):
            message = messages[-1]
        else:
            raise ValueError("No message found in input")

        outputs = []

        # 并行执行所有工具调用
        tasks = []
        for tool_call in message.tool_calls:
            if tool_call.get("args") and "query" in tool_call["args"]:
                query = tool_call["args"]["query"]
                log.info(f"开始从上下文中检索：{query}")
            else:
                query = inputs.get("input_text")

            # 使用异步调用
            task = self.tools_by_name[tool_call["name"]].ainvoke(
                {"query": query, "user_name": inputs.get("user")}
            )
            tasks.append((tool_call, task))

        # 等待所有异步调用完成
        tool_results = await asyncio.gather(
            *[task for _, task in tasks], return_exceptions=True
        )

        for (tool_call, _), tool_result in zip(tasks, tool_results):
            if isinstance(tool_result, Exception):
                tool_result = f"工具执行错误: {str(tool_result)}"

            outputs.append(
                ToolMessage(
                    content=str(tool_result),
                    name=tool_call["name"],
                    tool_call_id=tool_call["id"],
                )
            )

        return {"messages": outputs}


def retriever_node(state: MultiModalRAGState):
    """检索 知识库并返回"""
    if state.get("input_type") == "only_image":
        log.info(f"开始从知识库中检索图片：{state.get('input_image')}")
        # 纯图片检索，只用 dense search
        embedding = vl_client.embed_text_with_images(
            "", [state.get("input_image")]
        )
        results = m_re.dense_search(embedding, limit=3)
    else:
        # 文本检索，用混合检索（dense + BM25）
        input_data = [{"text": state.get("input_text")}]
        ok, embedding, _, _ = embed_for_knowledge_base(input_data)
        if ok:
            results = m_re.hybrid_search(embedding, state.get("input_text"), limit=3)
        else:
            results = []

    log.info(f"从知识库中检索到的结果：{results}")

    # 返回文档内容
    images = []
    docs = []
    for hit in results:
        # 提取图片路径（image_paths 是 JSON 数组字符串）
        image_paths_str = hit.get("image_paths", "")
        if image_paths_str and image_paths_str != "[]":
            import json
            paths = json.loads(image_paths_str) if isinstance(image_paths_str, str) else image_paths_str
            images.extend(paths)
        docs.append(
            {
                "text": hit.get("text"),
                "filename": hit.get("filename"),
                "image_paths": image_paths_str,
                "title": hit.get("title"),
            }
        )

    # 返回并更改状态（最多传2张图片，避免LLM超时）
    return {"context_retrieved": docs, "image_retrieved": images[:2]}