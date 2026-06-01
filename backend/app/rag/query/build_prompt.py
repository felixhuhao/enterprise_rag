"""Build numbered context and prompt for LLM."""

from __future__ import annotations

import logging

from langgraph.graph.state import RunnableConfig

from app.rag.query.config import QueryConfig, get_query_config
from app.rag.query.planner import get_query_plan, plan_budget
from app.rag.query.state import QueryState

logger = logging.getLogger(__name__)

ANSWER_PROMPT = """\
你是企业文档知识库助手。基于以下检索到的上下文回答用户问题。

要求：
1. 回答必须基于上下文，不要编造信息
2. 引用上下文时使用 [C1]、[C2] 等编号
3. 数值类回答必须标注来源编号
4. 如果上下文中没有相关信息，直接说明
5. 使用 Markdown 格式
6. 上下文中可能包含 [图片描述：...] 标记，这是对原始文档中图表/图片的文字转述，可以像普通文本一样引用

上下文：
{context}

用户问题：{query}"""

ANSWER_PROMPT_MULTI = """\
你是企业文档知识库助手。用户的问题涉及多个实体，请基于以下检索到的上下文回答。

要求：
1. 按实体分组回答，使用标题或列表区分每个实体的信息
2. 如果涉及对比，请用表格或对比列表呈现
3. 引用上下文时使用 [C1]、[C2] 等编号
4. 数值类回答必须标注来源编号
5. 如果某个实体在上下文中没有相关信息，直接说明
6. 使用 Markdown 格式

上下文：
{context}

用户问题：{query}"""

ANSWER_PROMPT_BROAD = """\
你是企业文档知识库助手。用户的问题涉及多个实体或全局检索，请基于以下检索到的上下文回答。

要求：
1. 按相关实体分组归纳信息，使用标题区分
2. 引用上下文时使用 [C1]、[C2] 等编号
3. 数值类回答必须标注来源编号
4. 如果上下文中没有相关信息，直接说明
5. 使用 Markdown 格式

上下文：
{context}

用户问题：{query}"""

FALLBACK_USED_INSTRUCTION = (
    "检索提示：由于原实体范围内证据不足，系统已扩大到全部可访问资料。"
    "回答时不要把扩大范围后找到的全局证据归因到原实体；如果证据不属于该实体，请明确说明。"
)

FALLBACK_BLOCKED_INSTRUCTION = (
    "检索提示：当前模式禁止从实体范围扩大到全局资料。"
    "如果当前上下文证据不足，请直接说明无法从资料确认。"
)

SYNTHESIS_INSTRUCTION = (
    "综合/比较提示：如果问题要求比较、关联、区别或一致性判断，"
    "请按“关联/相同点、区别、关键数值或时限”组织答案，并分别引用对应证据。"
)

STRICT_EVIDENCE_INSTRUCTION = (
    "严格证据模式：只能回答上下文直接支持的信息。"
    "如果资料只支持相关事实但缺少目标字段，请先列出已被资料直接支持的相关事实，"
    "再明确说明缺少的信息；不要根据比例、时间单位或常识推断缺失数值。"
)

SYNTHESIS_QUERY_MARKERS = (
    "比较", "关联", "区别", "异同", "一致", "不同", "分别", "各自", "对比",
)


def build_prompt_node(state: QueryState, config: RunnableConfig) -> dict:
    """组装编号上下文 [C1]/[C2]... + 构建 prompt。表格按三层策略标注。"""
    cfg = get_query_config(config)
    context_map: dict[str, dict] = {}
    context_parts: list[str] = []

    for i, result in enumerate(state.get("search_results", []), start=1):
        cid = f"C{i}"
        context_map[cid] = {
            "chunk_id": result.get("chunk_id"),
            "chunk_key": result.get("chunk_key", ""),
            "document_id": result.get("document_id", ""),
            "file_title": result.get("file_title", ""),
            "entity_name": result.get("entity_name", ""),
            "section_title": result.get("section_title", ""),
            "page": result.get("page"),
            "source_type": result.get("source_type", ""),
            "table_id": result.get("table_id", ""),
            "image_paths": result.get("image_paths", []),
            "context_expanded_chunk_ids": result.get("context_expanded_chunk_ids", []),
            "context_expand_parts": result.get("context_expand_parts", []),
        }
        header = _build_header(result, cid, cfg)
        context_parts.append(f"{header}\n{result.get('content', '')}")

    budget = plan_budget(state, config)
    max_chars = int(budget.get("max_context_chars") or 0)
    if max_chars > 0:
        context_parts, context_map = _truncate_context_parts(context_parts, context_map, max_chars)

    context_text = "\n\n---\n\n".join(context_parts)
    query = state.get("rewritten_query") or state["query"]

    plan = get_query_plan(state, config)
    prompt_policy = plan.get("prompt_policy") or {}
    template_name = prompt_policy.get("template")
    if template_name == "multi_entity":
        template = ANSWER_PROMPT_MULTI
    elif template_name == "broad":
        template = ANSWER_PROMPT_BROAD
    else:
        template = ANSWER_PROMPT

    prompt = template.format(context=context_text, query=query)
    fallback_info = state.get("fallback_info") or {}
    if fallback_info.get("used"):
        prompt += f"\n\n{FALLBACK_USED_INSTRUCTION}"
    elif fallback_info.get("blocked"):
        prompt += f"\n\n{FALLBACK_BLOCKED_INSTRUCTION}"
    if _needs_synthesis_instruction(query):
        prompt += f"\n\n{SYNTHESIS_INSTRUCTION}"
    if prompt_policy.get("strict_evidence"):
        prompt += f"\n\n{STRICT_EVIDENCE_INSTRUCTION}"

    return {"context_text": prompt, "context_map": context_map, "status": "prompted"}


def _needs_synthesis_instruction(query: str) -> bool:
    return any(marker in query for marker in SYNTHESIS_QUERY_MARKERS)


def _truncate_context_parts(
    context_parts: list[str],
    context_map: dict[str, dict],
    max_chars: int,
) -> tuple[list[str], dict[str, dict]]:
    """Limit context by chunk boundary so chunk content is never cut mid-text."""
    truncated_parts: list[str] = []
    total = 0
    separator_len = len("\n\n---\n\n")

    for part in context_parts:
        next_len = len(part) if not truncated_parts else separator_len + len(part)
        if total + next_len > max_chars:
            break
        truncated_parts.append(part)
        total += next_len

    if context_parts and not truncated_parts:
        logger.warning(
            "Context budget kept zero chunks because first chunk exceeds max_context_chars: "
            "max_context_chars=%d first_chunk_chars=%d",
            max_chars,
            len(context_parts[0]),
        )

    kept_ids = {f"C{i}" for i in range(1, len(truncated_parts) + 1)}
    truncated_map = {cid: meta for cid, meta in context_map.items() if cid in kept_ids}
    return truncated_parts, truncated_map


def _build_header(result: dict, cid: str, cfg: QueryConfig) -> str:
    """构建上下文条目标题，表格按 token 大小分层标注。"""
    file_title = result.get("file_title", "")
    entity_name = result.get("entity_name", "")
    section = result.get("section_title", "")
    base = f"[{cid}] 文件: {file_title} | 章节: {section}"
    if entity_name:
        base = f"{base} | 实体: {entity_name}"

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
