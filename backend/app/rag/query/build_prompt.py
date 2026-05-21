"""Build numbered context and prompt for LLM."""

from __future__ import annotations

from langgraph.graph.state import RunnableConfig

from app.rag.query.config import QueryConfig, get_query_config
from app.rag.query.state import QueryState

ANSWER_PROMPT = """\
你是金融文档分析助手。基于以下检索到的上下文回答用户问题。

要求：
1. 回答必须基于上下文，不要编造信息
2. 引用上下文时使用 [C1]、[C2] 等编号
3. 数值类回答必须标注来源编号
4. 如果上下文中没有相关信息，直接说明
5. 使用 Markdown 格式

上下文：
{context}

用户问题：{query}"""


def build_prompt_node(state: QueryState, config: RunnableConfig) -> dict:
    """组装编号上下文 [C1]/[C2]... + 构建 prompt。表格按三层策略标注。"""
    cfg = get_query_config(config)
    context_map: dict[str, dict] = {}
    context_parts: list[str] = []

    for i, result in enumerate(state.get("search_results", []), start=1):
        cid = f"C{i}"
        context_map[cid] = {
            "document_id": result.get("document_id", ""),
            "file_title": result.get("file_title", ""),
            "section_title": result.get("section_title", ""),
            "table_id": result.get("table_id", ""),
            "source_type": result.get("source_type", ""),
        }
        header = _build_header(result, cid, cfg)
        context_parts.append(f"{header}\n{result.get('content', '')}")

    context_text = "\n\n---\n\n".join(context_parts)
    prompt = ANSWER_PROMPT.format(context=context_text, query=state.get("rewritten_query") or state["query"])

    return {"context_text": prompt, "context_map": context_map, "status": "prompted"}


def _build_header(result: dict, cid: str, cfg: QueryConfig) -> str:
    """构建上下文条目标题，表格按 token 大小分层标注。"""
    file_title = result.get("file_title", "")
    section = result.get("section_title", "")
    base = f"[{cid}] 文件: {file_title} | 章节: {section}"

    source_type = result.get("source_type", "")
    if source_type not in ("table_summary", "table_full", "table_row_group"):
        return base

    tokens = result.get("table_tokens") or 0
    raw_path = result.get("raw_table_path", "")

    if tokens <= cfg.table_full_token_limit:
        tier = "完整表格"
    elif tokens <= cfg.table_medium_token_limit:
        tier = "中等表格 | 完整原始数据可按路径追溯"
        if raw_path:
            tier += f": {raw_path}"
    else:
        tier = "大型表格 | 仅展示部分行"

    return f"{base} | [{tier}]"
