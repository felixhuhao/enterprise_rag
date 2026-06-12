# Prompt Reliability Audit

**Date:** 2026-06-11
**Scope:** Full codebase scan of all LLM prompt templates and prompt construction
**Total Findings:** 15 across 7 source files

All prompts in the system are monolingual Chinese, targeting enterprise document RAG. The system has reasonable code-level fallback handling, but the prompts themselves exhibit several systemic reliability issues.

---

## Unreliability Pattern Legend

| Code | Pattern |
|------|---------|
| A | Missing output format specification |
| B | No output parsing instructions for edge cases |
| C | Vague/ambiguous instructions |
| D | No fallback/failure handling in prompt |
| E | Overly long/complex prompts |
| F | Missing examples (few-shot) |
| H | Unbounded output (no length constraint) |
| I | Language mixing |
| J | Hardcoded domain assumptions |
| K | No role/persona definition |
| L | Fragile output parsing |
| N | Missing guardrails |

---

## HIGH Severity

### Finding 1: Main Answer Generation Prompt (ANSWER_PROMPT)

**File:** `backend/app/rag/query/build_prompt.py`
**Lines:** 15-30

```
你是企业文档知识库助手。基于以下检索到的上下文回答用户问题。

要求：
1. 回答必须基于上下文，不要编造信息
2. 引用上下文时使用 [C1]、[C2] 等编号
3. 数值类回答必须标注来源编号
4. 每个事实性或数值性结论句末都必须带至少一个来源编号，不要只写"根据上下文"而不标引用
5. 如果上下文中没有相关信息，直接说明
6. 使用 Markdown 格式
7. 上下文中可能包含 [图片描述：...] 标记，这是对原始文档中图表/图片的文字转述，可以像普通文本一样引用

上下文：
{context}

用户问题：{query}
```

**Patterns:** A, H, N, K

**Concerns:**
- **(H) No length constraint.** No `max_tokens` set on the LLM call at `generate.py:27`. Model could produce extremely verbose or terse responses.
- **(A) Ambiguous format.** "Use Markdown" but no specification of structure (headings? bullets? prose?). Different invocations produce wildly different structures.
- **(N) No confidence guardrail.** No instruction for handling contradictory information across context chunks.
- **(K) Minimal persona.** "You are an enterprise document knowledge assistant" with no further tone/audience/detail-level definition.

---

### Finding 2: Multi-Entity Answer Prompt (ANSWER_PROMPT_MULTI)

**File:** `backend/app/rag/query/build_prompt.py`
**Lines:** 32-47

```
你是企业文档知识库助手。用户的问题涉及多个实体，请基于以下检索到的上下文回答。

要求：
1. 按实体分组回答，使用标题或列表区分每个实体的信息
2. 如果涉及对比，请用表格或对比列表呈现
3. 引用上下文时使用 [C1]、[C2] 等编号
...
```

**Patterns:** A, H, N

**Concerns:**
- Same core issues as Finding 1.
- **"Use headings or lists"** is ambiguous. Could request a specific heading format (e.g., `### Entity Name`) for deterministic parsing.
- Multi-entity responses increase risk of model confusion about organization.

---

### Finding 3: Broad/Discovery Answer Prompt (ANSWER_PROMPT_BROAD)

**File:** `backend/app/rag/query/build_prompt.py`
**Lines:** 49-63

```
你是企业文档知识库助手。用户的问题涉及多个实体或全局检索，请基于以下检索到的上下文回答。

要求：
1. 按相关实体分组归纳信息，使用标题区分
...
```

**Patterns:** A, H, C

**Concerns:**
- **(C) "Group by relevant entities"** is vague when discovery mode returns results from many entities. The model must guess the granularity.
- Discovery queries inherently return diverse results; without strict formatting rules, the LLM produces inconsistent structures.

---

### Finding 4: HyDE Hypothetical Document Prompt

**File:** `backend/app/rag/query/hyde_search.py`
**Lines:** 38-41

```python
HYDE_PROMPT = (
    "请根据以下企业文档问题，生成一段可能出现在相关文档中的假设性回答。"
    "回答应覆盖关键术语、实体、时间、数值或结论，但不要输出解释过程：\n\n{query}"
)
```

**Patterns:** A, F, H, L

**Concerns:**
- **(A) No format/length specification.** Output is used as an embedding query but could vary wildly.
- **(F) Zero examples.** Model must infer what "a hypothetical answer that might appear in relevant documents" means.
- **(L) Raw output used verbatim** (`hypothetical_doc = response.content`). If model adds preamble like "Here is the hypothetical answer:", it pollutes the embedding.
- **(H) No length constraint.** Very long HyDE outputs degrade embedding quality.

---

### Finding 5: Groundedness Check Prompt

**File:** `backend/app/rag/query/groundedness.py`
**Lines:** 19-52

This is the longest and most complex prompt in the system. It contains:
- Multiple rule sets (factual vs. no_answer claim types)
- Special-case sub-rules for no_answer detection
- Detailed claim extraction instructions
- Citation ID extraction rules
- JSON output format specification

```
输出严格 JSON，不要输出任何 markdown fence 之外的文字：
{"claims":[{"claim":"...","claim_type":"factual","verdict":"supported","evidence":"...","citation_ids":["C1"]}]}
```

**Patterns:** E, L, H, C

**Concerns:**
- **(E) Overly complex.** Longest prompt in the system with nested rule sets. Increases risk of model missing or misunderstanding instructions.
- **(L) Fragile despite "strict JSON" instruction.** Parser `_parse_groundedness` has 3 fallback strategies (direct parse, code fence extraction, regex stripping), confirming known format unreliability.
- **(H) No `max_tokens`.** With up to 8+ claims, each with evidence text, output could be very large.
- **(C) "Most important claims"** is subjective. What counts as important varies by context.
- **(N) No `temperature=0`** for this deterministic judging task. Uses LangChain default.

---

### Finding 6: Generate Answer Node — Missing Output Controls

**File:** `backend/app/rag/query/generate.py`
**Lines:** 12-31

```python
_chat_llm = ChatOpenAI(
    model=settings.CHAT_MODEL,
    api_key=settings.DEEPSEEK_API_KEY,
    base_url=settings.DEEPSEEK_BASE_URL,
    timeout=settings.CHAT_TIMEOUT,
    max_retries=3,
)
```

**Patterns:** H, K, N

**Concerns:**
- **(H) No `max_tokens`.** Model generates until natural stop or provider default limit. Could be thousands of tokens.
- **(N) No `temperature` explicitly set.** Relies on LangChain default (which varies). For factual RAG answers, lower temperature would be more appropriate.
- **(K) No system-level persona.** The prompt IS the system message with no additional behavioral guardrails.

---

## MEDIUM Severity

### Finding 7: Query Expansion Prompt

**File:** `backend/app/rag/query/query_expansion.py`
**Lines:** 19-28

```
根据以下企业文档检索问题，生成 {count} 条不同表述的检索查询。
要求：
1. 使用同义词、相关术语、不同角度重新表述
2. 保留关键实体名称和数值不变
3. 每条查询独立成行，不要编号
4. 不要解释，只输出查询

原始问题：{query}
```

**Patterns:** F, L, H

**Concerns:**
- **(F) Zero examples** of good expanded queries.
- **(L) Parsed by `content.splitlines()`** with regex stripping. If model uses comma/semicolon separation, parser fails silently and returns fewer expansions.

---

### Finding 8: Rerank Scoring Prompt

**File:** `backend/app/rag/query/rerank.py`
**Lines:** 32-42

```
你是一个搜索结果相关性评分器。根据用户问题，对每条检索结果打分（0 到 1）。

评分标准：
- 1.0: 直接回答了问题的具体数据或事实
- 0.7: 包含相关但不够具体的信息
- 0.4: 话题相关但缺少关键信息
- 0.1: 几乎无关

严格按 JSON 数组格式输出，只输出分数数组，不要其他文字。
示例：[0.9, 0.7, 0.3, 0.1]
```

**Patterns:** L, F, B, N

**Concerns:**
- **(F) One example output only**, no paired input-output examples. Model must infer scoring from criteria alone.
- **(L) `json.loads()` on raw response.** `JSONDecodeError` triggers fallback scores — score inaccuracy without visible failure.
- **(N) No instruction** for edge cases: all relevant? all irrelevant? inconsistent batch sizes?

---

### Finding 9: Image Description Prompt

**File:** `backend/app/rag/parsing/image_describer.py`
**Lines:** 21-27

```python
VL_PROMPT = """\
请用中文详细描述这张图片的内容。

如果是图表（折线图/柱状图/饼图等），请描述数据趋势和关键数值。
如果是流程图/架构图，请描述结构关系和关键组件。
如果是截图/照片，请描述主要内容和关键信息。
请输出结构化的文字描述，200-500字。"""
```

**Patterns:** A, D, F, H

**Concerns:**
- **(A) "Structured text description"** is ambiguous. Paragraphs? Bullet points? JSON? Different formats make descriptions inconsistent for downstream chunk embedding.
- **(D) No instruction** for unclear/corrupted/unrecognizable images.
- **(F) Zero examples** for any image type.
- **(H) "200-500 characters"** but no `max_tokens` enforced. Chinese character count != token count.

---

### Finding 10: LLM Judge Prompt

**File:** `backend/scripts/eval_golden/judge.py`
**Lines:** 11-44

```
你是一个 RAG 系统评估助手。请综合判断以下回答的质量。
...
输出严格 JSON（不要 markdown 代码块）：
{
  "score": 0.0-1.0,
  "verdict": "pass" | "warn" | "fail",
  "missing_points": ["未覆盖的要点"],
  "unsupported_claims": ["无引用支撑的具体声明"],
  "reason": "一句话说明理由"
}
```

**Patterns:** L, N, I

**Concerns:**
- **(L) Fragile JSON parsing.** Parser `_parse_judge_response` has 3 fallback strategies + regex fallback, confirming known format unreliability. Retry logic (3 attempts) adds latency.
- **(N) No instruction** for empty answers or unanswerable questions.
- **(I) Mixed English JSON keys** with Chinese instructions/values. Could confuse model about output language.

---

### Finding 11: Synthesis Instruction Injection

**File:** `backend/app/rag/query/build_prompt.py`
**Lines:** 88-90, 150-151

```python
SYNTHESIS_QUERY_MARKERS = (
    "比较", "关联", "区别", "异同", "一致", "不同", "分别", "各自", "对比",
)
```

When triggered, adds synthesis instructions to the prompt via `_needs_synthesis_instruction()`.

**Patterns:** C, J

**Concerns:**
- **(C) False positives.** "不同的部门有不同的审批流程" is not a comparison query but contains "不同" and "分别". Adds irrelevant instructions, potentially confusing the model.
- **(J) Chinese-only markers.** English queries like "compare" or "difference" never trigger synthesis.

---

### Finding 12: Stream Chat — Unbounded History Injection

**File:** `backend/app/api/query_chat.py`
**Lines:** 351-357

```python
messages = [SystemMessage(content=require_context_text(state))]
for msg in history:
    if msg["role"] == "user":
        messages.append(HumanMessage(content=msg["content"]))
    elif msg["role"] == "assistant":
        messages.append(AIMessage(content=msg["content"]))
messages.append(HumanMessage(content=require_query(state)))
```

**Patterns:** E, N

**Concerns:**
- **(E) Context window bloat.** Full prompt + 10 history messages can exceed model context window.
- **(N) No filtering or summarization** of old turns. Old conversations about different topics could confuse the model about current context.

---

### Finding 13: Groundedness LLM Call — No Determinism

**File:** `backend/app/rag/query/groundedness.py`
**Lines:** 92-98

```python
judge_llm = ChatOpenAI(
    model=settings.CHAT_MODEL,
    api_key=settings.DEEPSEEK_API_KEY,
    base_url=settings.DEEPSEEK_BASE_URL,
    timeout=cfg.groundedness_timeout_sec,
    max_retries=1,
)
```

**Patterns:** H, N

**Concerns:**
- **(H) No `max_tokens`.** Large claim sets produce very large JSON.
- **(N) No `temperature=0`.** For a deterministic judging task, this should be pinned to 0.
- New `ChatOpenAI` instance created per request — inconsistent with other modules that use module-level singletons.

---

## LOW Severity

### Finding 14: Context Header Construction

**File:** `backend/app/rag/query/build_prompt.py`
**Lines:** 184-209

```python
base = f"[{cid}] 文件: {file_title} | 章节: {section}"
if entity_name:
    base = f"{base} | 实体: {entity_name}"
```

**Patterns:** I, J

**Concerns:**
- Metadata labels in Chinese ("文件", "章节", "实体") assume Chinese document domain.
- Tier labels "完整表格", "中等表格", "大型表格" are domain-specific.
- Low severity: these are consistent with the Chinese-focused system design.

---

### Finding 15: Duplicate Synthesis Markers

**File:** `backend/app/rag/query/planner.py:21-23` AND `backend/app/rag/query/build_prompt.py:88-90`

Same `SYNTHESIS_QUERY_MARKERS` tuple defined in two files.

**Concerns:**
- Risk of divergence when one copy is updated without the other.
- Related to the keyword matching audit (Finding 5 in keyword_matching_audit.md).

---

## Cross-Cutting Themes

### 1. No `max_tokens` Anywhere
None of the LLM calls (generate, rerank, HyDE, expansion, groundedness, image description, judge) set `max_tokens`. This leads to unpredictable output lengths and potential token waste.

### 2. Zero Few-Shot Examples
None of the 9 prompts include paired input-output examples. All rely on zero-shot instruction following, which is less reliable for structured output tasks (JSON, scoring, expansion).

### 3. Fragile JSON Parsing Is a Known Problem
Both the judge and groundedness prompts request "strict JSON" but both have 3-level fallback parsers. This confirms the prompts regularly produce non-JSON output despite instructions.

### 4. Temperature Inconsistency

| Module | Temperature |
|--------|------------|
| Rerank | `0.0` |
| HyDE | `0.3` |
| Expansion | `0.3` |
| Judge | `0.1` |
| Generate | LangChain default (unspecified) |
| Groundedness | LangChain default (unspecified) |

Temperature was not systematically considered. Factual/judging tasks (generate, groundedness) should use low or zero temperature.

### 5. Monolingual Chinese Only
All prompts are Chinese-only. No English prompts or bilingual handling. The system cannot serve non-Chinese queries effectively.

### 6. No Confidence/Calibration Instructions
No prompt instructs the model to express uncertainty or provide confidence levels. The system has no way to signal low-confidence answers to users.

---

## Summary Table

| # | Prompt | File | Lines | Patterns | Severity |
|---|--------|------|-------|----------|----------|
| 1 | ANSWER_PROMPT | build_prompt.py | 15-30 | A, H, N, K | HIGH |
| 2 | ANSWER_PROMPT_MULTI | build_prompt.py | 32-47 | A, H, N | HIGH |
| 3 | ANSWER_PROMPT_BROAD | build_prompt.py | 49-63 | A, H, C | HIGH |
| 4 | HYDE_PROMPT | hyde_search.py | 38-41 | A, F, H, L | HIGH |
| 5 | GROUNDEDNESS_PROMPT | groundedness.py | 19-52 | E, L, H, C | HIGH |
| 6 | generate_answer_node | generate.py | 12-31 | H, K, N | HIGH |
| 7 | EXPANSION_PROMPT | query_expansion.py | 19-28 | F, L, H | MEDIUM |
| 8 | RERANK_SYSTEM | rerank.py | 32-42 | L, F, B, N | MEDIUM |
| 9 | VL_PROMPT | image_describer.py | 21-27 | A, D, F, H | MEDIUM |
| 10 | JUDGE_PROMPT | judge.py | 11-44 | L, N, I | MEDIUM |
| 11 | Synthesis markers | build_prompt.py | 88-90 | C, J | MEDIUM |
| 12 | Stream chat history | query_chat.py | 351-357 | E, N | MEDIUM |
| 13 | Groundedness LLM call | groundedness.py | 92-98 | H, N | MEDIUM |
| 14 | Context headers | build_prompt.py | 184-209 | I, J | LOW |
| 15 | Duplicate synthesis markers | planner.py + build_prompt.py | 21-23, 88-90 | — | LOW |
