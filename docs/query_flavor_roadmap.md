# Query Flavor Roadmap

This roadmap describes the next retrieval-quality work after the current feature freeze. The goal is to improve recall, precision, and evidence control without turning the system into an uncontrolled agent or a pile of independent toggles.

## Core Decision

Do the Query Flavor refactor first, but keep the first phase limited to the control layer.

The system should expose only two high-level controls:

```text
retrieval_flavor = balanced | exact | recall | discovery
strict_evidence = true | false
```

Internal routing such as broad search, multi-entity search, table handling, fallback, query expansion, and small-to-big context should remain implementation details. Users should choose intent, not algorithms.

## Phase 0: Baseline And Challenge Set

Before changing retrieval behavior, freeze a reusable baseline.

Use the current 18 Markdown documents as `demo_corpus_v1`. This is enough for the first challenge set. Do not generate a larger corpus yet unless the current files fail to cover the needed query types.

### Corpus Requirements

The 18 Markdown files should cover, or be extended only slightly to cover:

- Multi-entity comparisons.
- Old policy vs new policy conflicts.
- Numeric clauses such as amounts, days, thresholds, SLA limits, and approval times.
- Cross-document questions involving policy, FAQ, runbook, meeting notes, or product docs.
- Alias and abbreviation queries such as API, SLA, department names, and company short names.
- No-answer questions.
- Discovery questions where the system must first find relevant entities, then query those entities.

### Evaluation Sets

Keep evaluation layered:

```text
smoke_set:
  verifies the system still works

challenge_set:
  exposes retrieval weaknesses

flavor_slices:
  groups cases by intended retrieval flavor
```

The challenge set does not need to pass fully before refactoring. Its job is to reveal where each flavor should help.

Recommended JSONL fields:

```json
{
  "id": "exact_policy_001",
  "query": "差旅住宿一线城市经理以下标准是多少？",
  "preferred_flavor": "exact",
  "strict_evidence": true,
  "tags": ["exact", "policy", "number"],
  "expected_documents": ["差旅与报销管理办法"],
  "expected_sections": ["住宿标准"],
  "expected_anchor_text": ["一线城市", "600 元/晚"],
  "should_answer": true
}
```

Do not depend only on Milvus `chunk_id` for expected evidence. Collection rebuilds can change auto ids. Prefer:

- `expected_documents`
- `expected_sections`
- `expected_anchor_text`
- stable `chunk_key` later, once fully reliable

### Phase 0 Metrics

Record these before the refactor:

- Answer Pass Rate.
- Hit@5.
- Hit@10.
- Citation Hit Rate.
- p95 latency.
- Slice-level results by tag and preferred flavor.

Run examples:

```text
eval --slice exact
eval --slice recall
eval --slice discovery
eval --slice strict
```

## Phase 1: Query Flavor Control Layer

Goal: centralize query behavior planning without changing the default answer quality.

Add a single planner that produces:

```text
QueryPlan:
  retrieval_flavor
  strict_evidence
  use_hyde
  use_query_expansion
  use_multi_hop
  fallback_policy
  budget
  prompt_policy
```

Initial behavior:

- `balanced`: current default path.
- `exact`: smaller budget, no HyDE, no query expansion, entity fallback disabled.
- `recall`: same as balanced for now; query expansion is added later.
- `discovery`: current constrained multi-hop discovery path.
- `strict_evidence`: independent evidence policy, not a retrieval flavor.

Important rule:

Do not scatter checks like `if exact` or `if recall` across nodes. Nodes should read the resolved `QueryPlan`.

## Phase 2: Controlled Entity Fallback

Goal: prevent entity-scoped queries from silently answering with unrelated global evidence.

Current risk:

```text
entity query -> weak entity-filtered results -> silently remove filter -> global results
```

Policy:

```text
exact:
  entity fallback disabled

balanced:
  entity fallback allowed with warning

recall:
  entity fallback allowed with warning

discovery:
  hop1 fallback disabled
  hop2 fallback limited and explicit

strict_evidence:
  entity fallback disabled

multi_explicit:
  global fallback disabled
  record missing evidence per entity
```

Add structured fallback state:

```text
fallback_info:
  used: bool
  blocked: bool
  type: entity_filter_to_global
  reason: low_score_or_insufficient_hits | entity_fallback_disabled
  original_filter: string
```

Prompt behavior:

- If fallback was used, tell the model the retrieval scope widened and it must not attribute global evidence to the original entity.
- If fallback was blocked and evidence is weak, prefer no-answer.

UI behavior:

- Show when the search scope widened, for example `星辰科技 -> 全部资料`.
- Show why fallback was used or blocked.

## Phase 3: Dynamic Retrieval Budget

Goal: allocate retrieval budget based on query intent instead of one static setting.

This is a policy layer, not a user-facing retrieval mode.

Resolved budget shape:

```text
RetrievalBudget:
  search_limit
  rrf_top_k
  rerank_candidate_k
  final_context_k
  max_context_chars
  per_entity_min_k
  reason
```

Initial defaults:

```text
exact:
  search_limit = 8
  rrf_top_k = 8
  rerank_candidate_k = 8
  final_context_k = 3
  max_context_chars = 5000

balanced + single/none:
  search_limit = 12
  rrf_top_k = 16
  rerank_candidate_k = 12
  final_context_k = 5
  max_context_chars = 8000

balanced + broad:
  search_limit = 24
  rrf_top_k = 32
  rerank_candidate_k = 24
  final_context_k = 8
  max_context_chars = 12000

recall:
  search_limit = 20 per expanded query
  rrf_top_k = 40
  rerank_candidate_k = 30
  final_context_k = 8
  max_context_chars = 14000

multi_explicit:
  per_entity_min_k = 8
  rrf_top_k = 40
  rerank_candidate_k = 30
  final_context_k = 8
  max_context_chars = 14000

discovery hop1:
  search_limit = 16
  rrf_top_k = 24
  rerank_candidate_k = 16
  final_context_k = evidence only
  max_context_chars = 8000

discovery hop2:
  search_limit = 10 per discovered entity
  rrf_top_k = 40
  rerank_candidate_k = 30
  final_context_k = 8
  max_context_chars = 14000
```

Safety caps:

```text
MAX_SEARCH_LIMIT = 40
MAX_RERANK_CANDIDATES = 30
MAX_CONTEXT_CHARS = 16000
```

Validation:

- Exact queries should get lower latency and less noise.
- Broad and multi-entity queries should improve Hit@10.
- Recall and discovery should stay within acceptable p95 latency.

## Phase 4: Small-to-Big Final Context

Goal: preserve precise anchor citations while giving the model enough neighboring context.

Default first version:

```text
context_expansion = small_to_big_final_only
small_to_big_window = 1
small_to_big_same_section_only = true
small_to_big_max_chars = 2400查询历史搜索/筛选	中（方便回溯）	低
```

Rules:

- Retrieval and rerank still operate on anchor chunks.
- Prompt construction may use expanded neighboring context.
- Citations should keep pointing to the anchor chunk.
- Trace should show expanded chunk ids.

Why this comes after budget:

- The budget decides how much context can safely fit.
- Small-to-big should not accidentally push prompts over the context cap.

## Phase 5: Query Expansion For Recall Flavor

Goal: improve recall for vague or synonym-heavy questions without changing the default path.

Only attach query expansion to `recall`.

Flow:

```text
entity_router
  -> rewrite
  -> query_expansion
  -> parallel_search
  -> rrf
  -> table_expand
  -> rerank
  -> prompt
  -> generate
```

Constraints:

- Generate 2-4 related search queries.
- Run hybrid search for each query in parallel.
- Merge by RRF and deduplicate by `chunk_id`.
- Do not combine query expansion with HyDE in the first version.
- Do not use this for discovery; discovery remains the multi-hop path.
- Show expanded queries and per-query hit counts in trace and retrieval test.

## Phase 6: Metrics By Flavor

Goal: make retrieval quality measurable, not subjective.

Add stats/eval reporting for:

- Hit@5.
- Hit@10.
- Citation Hit Rate.
- Answer Pass Rate.
- p95 latency.
- Results grouped by `retrieval_flavor`.
- Results grouped by `strict_evidence`.

Recommended page placement:

- Online query health stays in the stats/monitoring page.
- Golden Set regression belongs in a separate regression evaluation page.

## Phase 7: Alias And Keyword Enrichment

Goal: improve Chinese enterprise recall for abbreviations, policy terms, and entity aliases.

Do this after Query Flavor is stable. This touches ingestion and metadata, so it is heavier.

First version:

- Add `entity_aliases` table.
- Match aliases in entity routing.
- Normalize alias hits to canonical `entity_name`.
- Show `matched_alias`, canonical entity, and alias source in trace.
- If one alias maps to multiple entities, mark ambiguous instead of choosing silently.

Defer until a planned index rebuild:

- Chunk-level keyword artifacts.
- `search_text = content + keywords + aliases`.
- Milvus BM25 over `search_text`.

## Phase 8: User-Friendly Terminology

Goal: keep backend terminology precise while making the UI understandable.

Public labels:

```text
balanced  -> 标准问答
exact     -> 精确查找
recall    -> 全面查找
discovery -> 关联查找

strict_evidence -> 仅基于资料回答
query_expansion -> 换几种说法查找
small_to_big    -> 补充上下文
fallback_used   -> 已扩大查找范围
fallback_blocked -> 未扩大查找范围
dense           -> 语义匹配
sparse / BM25   -> 关键词匹配
hybrid          -> 语义 + 关键词
rerank          -> 相关性重排
groundedness_score -> 资料支持度
```

Main chat should show intent-level controls. Debug panels can still expose raw fields like `entity_mode`, `search_mode`, `fallback_info`, RRF rank, and rerank scores.

## Recommended Execution Order

1. Freeze `demo_corpus_v1` and create `challenge_golden_set_v1.jsonl`.
2. Add slice-aware eval fields and baseline metrics.
3. Add `QueryPlan` and `retrieval_flavor` control layer.
4. Add controlled entity fallback.
5. Add dynamic retrieval budget.
6. Add small-to-big final context expansion.
7. Add query expansion for `recall`.
8. Add flavor-level metrics and regression page.
9. Add alias matching.
10. Polish user-facing terminology.

## Success Criteria

The refactor is successful if:

- `balanced` remains as good as the current default.
- `exact` reduces wrong-scope answers and improves precision for clauses/numbers.
- `recall` improves Hit@10 and Citation Hit Rate on recall-heavy cases.
- `discovery` remains bounded, inspectable, and evidence-backed.
- `strict_evidence` prevents unsupported answers without becoming a separate pipeline.
- p95 latency stays explainable by flavor.

## Phase 9: Chunk Keyword Generation

Goal: extract searchable keywords from each chunk during ingestion, improving BM25 recall for Chinese enterprise terminology without touching Milvus schema.

### Design

#### Rule-based extraction（P1，零 LLM 成本）

从每个 text chunk 提取关键词，存为 parsed artifact。不进 Milvus，仅用于：
- Document Detail 页面 chunk 表显示
- 未来 search_text 合并（Phase 10）

提取规则：
- Markdown heading（`#` 标题）→ 关键词
- **粗体文本**（`**xxx**`）→ 关键词
- 书名号内容（`《xxx》`）→ 关键词
- 以"办法/制度/流程/规范/标准/政策/指南/规定/条例"结尾的短语 → 关键词
- 大写缩写（`SLA`、`API`、`BM25`）→ 关键词
- 中文数字+单位组合（`600 元/晚`、`3 天`）→ 关键词
- 去重 + 限制每 chunk 最多 8 个

#### Storage

`parsed/{document_id}/chunk_keywords.json`:
```json
[
  {"chunk_key": "ck_xxx", "keywords": ["差旅管理办法", "住宿标准", "600 元/晚"]},
  ...
]
```

chunk dict 新增 `"keywords": list[str]` 字段，写入 chunks.json。

#### Implementation

**新文件**: `backend/app/rag/chunking/keyword_extractor.py`
- `extract_keywords(content: str, section_title: str) -> list[str]` — 纯规则，无 LLM
- `enrich_chunks_with_keywords(chunks: list[dict]) -> list[dict]` — 批量处理

**修改**: `backend/app/rag/ingestion/graph.py`
- 新节点 `enrich_keywords` 插入在 `chunk` 和 `embed_and_save` 之间
- Graph edge: `chunk → enrich_keywords → embed_and_save`

**修改**: `backend/app/rag/ingestion/config.py`
- `keyword_enabled: bool = True`

#### Frontend

**修改**: `frontend/src/components/documents/DocumentDetailView.vue`
- chunk 表加 "关键词" 列，显示为 tags/chips

#### 不做

- 不加 LLM 关键词生成（P1 纯规则够用）
- 不改 Milvus schema（keywords 暂不进 Milvus）
- 不改搜索逻辑（keywords 暂不参与检索）

#### 验证

1. `pytest backend/tests/unit/ -v`
2. 重新 ingest demo 文档，确认 chunks.json 包含 keywords
3. Document Detail 页面确认关键词显示
4. 抽查关键词质量：差旅文档应有 "住宿标准"、"600 元" 等

---

## Phase 10: Doc2Query — Chunk Question Generation

Goal: generate 3-5 answerable questions per text chunk, index in a companion Milvus collection, and use as a recall bridge during retrieval. Only active for `recall` flavor initially.

### Design

#### Ingestion

对每个 text chunk，LLM 生成 3-5 个该 chunk 能回答的问题。存入 companion collection `general_doc2query`。

```
chunk
  → [keyword extraction]
  → embed_and_save (original chunks → general_documents)
  → doc2query_generate
  → doc2query_embed_and_save (generated questions → general_doc2query)
```

#### Companion Collection Schema

```
general_doc2query:
  query_id         INT64 auto_id
  parent_chunk_key VARCHAR(128)   -- 指回原 chunk
  document_id      VARCHAR(128)
  entity_name      VARCHAR(512)
  file_title       VARCHAR(65535)
  section_title    VARCHAR(65535)
  page             INT64
  part             INT8
  question         VARCHAR(65535) -- 生成的问题
  dense            FLOAT_VECTOR   -- 问题 embedding
  sparse           SPARSE_FLOAT_VECTOR -- 问题 BM25
```

#### Query Flow

```
recall flavor:
  search(original_query) → general_documents     (现有)
  doc2query_search(original_query) → general_doc2query  (新增)
  merge: 按 parent_chunk_key 去重，保留最高分
  rerank(original_chunk_content)  (只用原 chunk content 做 rerank)
  → 后续 pipeline 不变
```

关键：retrieval 用 question 作桥梁，但 rerank、prompt、citation 全部用原 chunk content。

#### LLM Prompt

```python
DOC2QUERY_PROMPT = """\
根据以下文档片段，生成 {count} 个该片段能够回答的检索问题。
要求：
1. 问题应使用用户可能的提问方式，而非文档原文
2. 涵盖不同角度（事实、数字、流程、对比）
3. 每个问题一行，不要编号
4. 不要生成片段无法回答的问题

文档片段：
{content}
"""
```

#### Config

**IngestionConfig** 新增：
```python
doc2query_enabled: bool = False      # 默认关闭，需手动开启
doc2query_questions_per_chunk: int = 3
doc2query_max_content_chars: int = 1800  # 超长 chunk 跳过
```

**QueryConfig** 新增：
```python
use_doc2query: bool = False          # query-time 开关
doc2query_weight: float = 0.3        # RRF 合并时 doc2query 路的权重
```

**Planner**：
- recall + `cfg.use_doc2query` → 启用 doc2query search
- 其他 flavor → 不启用

#### Implementation Files

**新建**:
- `backend/app/rag/ingestion/doc2query.py` — LLM 生成问题
- `backend/app/rag/vectorstores/doc2query_milvus.py` — companion collection 管理
- `backend/app/rag/query/doc2query_search.py` — query-time 搜索节点
- `backend/tests/unit/test_keyword_extractor.py`
- `backend/tests/unit/test_doc2query.py`

**修改**:
- `backend/app/rag/ingestion/graph.py` — 新节点 doc2query_generate + doc2query_embed
- `backend/app/rag/ingestion/config.py` — 新配置字段
- `backend/app/rag/query/config.py` — query-time 开关
- `backend/app/rag/query/planner.py` — recall 启用 doc2query
- `backend/app/rag/query/rrf_fusion.py` — 合并 doc2query 结果
- `backend/app/rag/query/graph.py` — run_query_graph 加 doc2query 路径
- `backend/app/api/query_chat.py` — SSE 路径
- `backend/app/services/retrieval_test_service.py` — 测试路径
- `frontend/...` — retrieval test 显示 doc2query 来源

#### Trace 输出

doc2query 命中的 chunk 在 retrieval_path 中显示 `doc2query` 标签：
```
"retrieval_path": "hybrid + doc2query + rerank"
```

retrieval-test 展示每个 doc2query 命中对应的匹配问题。

#### 不做

- 不在 balanced/exact/discovery 启用（P1 只给 recall）
- 不把生成问题混入原 chunk content
- 不自动开放，需要 ingest config 显式开启
- 不做 question quality 过滤（P1信任 LLM，后续可通过 retrieval-test 验证）

#### 验证

1. 开启 doc2query ingest config，重新 ingest demo 文档
2. 确认 `general_doc2query` collection 有数据
3. retrieval-test 选 recall flavor，确认 doc2query 标签出现
4. 对比有/无 doc2query 的 Hit@5/Hit@10
5. 确认 citation 仍指向原 chunk（非 question）
6. 确认 balanced/exact 不触发 doc2query
