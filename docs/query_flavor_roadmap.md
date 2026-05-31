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

Implementation status: Phases 0-8 are implemented. The next quality work should move from query-time tricks to ingestion-time enrichment, because some recall failures come from source chunks using different wording than user questions.

Example failure:

```text
Query: 星辰科技有哪些制度文件提到了涉及金额审批的阈值？分别是什么金额？
Missed evidence: 12_年度培训计划_2026 > 五、外部培训管理
Source wording: 单次费用超过10,000元需VP级别审批，超过30,000元需CEO审批
```

This is not mainly a rerank problem. The correct chunk must first become easier to retrieve.

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
11. Add ingestion-time chunk search enrichment and rebuild the demo index.
12. Add tag governance and UI exposure rules.
13. Run a Section Probe Retrieval experiment if long-document/long-section recall still fails.
14. Add Doc2Query only if search enrichment and section probes are not enough for recall-heavy cases.

## Success Criteria

The refactor is successful if:

- `balanced` remains as good as the current default.
- `exact` reduces wrong-scope answers and improves precision for clauses/numbers.
- `recall` improves Hit@10 and Citation Hit Rate on recall-heavy cases.
- `discovery` remains bounded, inspectable, and evidence-backed.
- `strict_evidence` prevents unsupported answers without becoming a separate pipeline.
- p95 latency stays explainable by flavor.

## Phase 9: Chunk Search Enrichment

Goal: improve recall for enterprise policy language by enriching each source chunk at ingestion time. This phase should make weakly worded but relevant chunks easier to retrieve, especially for amount thresholds, approval rules, dates, roles, aliases, and policy names.

This is the right place to fix cases like `recall_agg_001`. Query expansion can help, but it is unstable when the source uses words like `单次费用超过` while the user asks for `金额审批阈值`.

### Execution Plan

1. Inspect the existing field flow.
   - Confirm which fields are produced by chunking.
   - Confirm which field is embedded for dense retrieval.
   - Confirm which field is used for sparse/BM25 retrieval.
   - Confirm which fields are returned by Milvus query/search and passed into rerank, prompt, citation, stats, and UI.

2. Add rule-based enrichment.
   - Generate `keywords`, `structured_tags`, and `search_text`.
   - Cover amount expressions, approval roles, threshold terms, section titles, policy names, aliases, and common enterprise terms.
   - Keep this deterministic and unit-tested; no LLM in Phase 9.

3. Wire enrichment into ingestion.
   - Insert enrichment after chunking and before vector persistence.
   - Persist enrichment into `chunks.json` and `chunk_enrichment.json`.
   - Keep source `content` unchanged.

4. Update Milvus schema and row mapping.
   - Add `search_text`, `keywords`, and `structured_tags`.
   - Dense vectors remain based on source `content`.
   - Sparse/BM25 vectors should be based on `search_text`.
   - Keep old-collection fallback schema-aware.

5. Update search compatibility.
   - Return enrichment fields when available.
   - Fall back to `content` when old collections do not have `search_text`.
   - Ensure rerank, prompt, citation, and stats still use source `content`.

6. Rebuild and verify the demo index.
   - Reingest demo documents.
   - Run `recall_agg_001` and recall slice.
   - Compare Hit@5, Hit@10, Citation Hit Rate, and latency before/after enrichment.

### Design

#### Rule-based enrichment（P1，no LLM cost）

For each text/table chunk, generate three artifact fields:

```json
{
  "keywords": ["外部培训管理", "单次费用", "VP审批", "CEO审批"],
  "structured_tags": ["amount_threshold", "approval_rule", "training_budget"],
  "search_text": "原始内容 + section_title + keywords + structured_tags + normalized_amount_phrases"
}
```

`content` stays unchanged and remains the only source shown to the LLM and citations. `search_text` is only for retrieval.

#### Enrichment Profile And Tag Linkage

Enrichment should not be treated as one universal rule set. The current enterprise finance/policy rules are valuable for this demo, but they are not suitable for unrelated corpora such as academic papers.

Supported profiles:

```python
chunk_enrichment_profile = "enterprise_policy"
# "none" | "general" | "enterprise_policy"
```

- `none`: do not add retrieval enrichment fields.
- `general`: add broadly useful lexical enrichment such as headings, bold text, book titles, acronyms, policy/document names, and normalized numeric/amount phrases.
- `enterprise_policy`: add `general` plus enterprise policy rules such as amount thresholds, approval roles, reimbursement, payment, budget, procurement, supplier, and deadline recall terms.

Profile selection is an ingestion-time decision because it changes persisted `search_text`, `keywords`, and `structured_tags`. Query-time auto selection is not enough unless multiple indexes/search_text fields are maintained.

Future tag-system linkage:

```python
def resolve_enrichment_profile(document_tags: list[str], override: str = "auto") -> str:
    if override != "auto":
        return override
    if "enterprise_policy" in document_tags:
        return "enterprise_policy"
    if "academic_paper" in document_tags:
        return "academic_paper"
    return "general"
```

Target behavior:

```text
document tags / collection tags
  -> resolve enrichment profile before ingestion
  -> persist enrichment_profile on chunks
  -> index search_text with the selected profile
  -> query uses the already-built representation
```

Upload/UI should eventually expose an override:

```text
Auto by tags
General
Enterprise policy
Off
```

This keeps enrichment explainable and correctable: admins can adjust tags or override the profile before reingestion.

提取规则：
- Markdown heading（`#` 标题）→ 关键词
- **粗体文本**（`**xxx**`）→ 关键词
- 书名号内容（`《xxx》`）→ 关键词
- 以"办法/制度/流程/规范/标准/政策/指南/规定/条例"结尾的短语 → 关键词
- 大写缩写（`SLA`、`API`、`BM25`）→ 关键词
- 中文数字+单位组合（`600 元/晚`、`3 天`）→ 关键词
- 金额表达（`10,000元`、`3万元`、`50万以上`）→ normalized amount tokens
- 审批表达（`需VP审批`、`CEO审批`、`CFO审批`、`总监签字`）→ `approval_rule`
- 阈值表达（`超过`、`以下`、`以上`、`以内`、`不低于`）→ `amount_threshold`
- 去重 + 限制每 chunk 最多 8 个

#### Search Text

`search_text` should include normalized recall terms that users are likely to ask:

```text
金额审批阈值
费用审批门槛
超过金额审批
审批权限
付款审批
预算审批
```

Only add these terms when the chunk actually contains matching amount + approval evidence. Do not globally append finance terms to every chunk.

#### Storage

`parsed/{document_id}/chunk_enrichment.json`:
```json
[
  {
    "chunk_key": "ck_xxx",
    "keywords": ["外部培训管理", "10,000元", "VP审批"],
    "structured_tags": ["amount_threshold", "approval_rule"],
    "search_text": "..."
  }
  ...
]
```

chunk dict should also include:

```python
keywords: list[str]
structured_tags: list[str]
search_text: str
```

These fields are persisted in `chunks.json` so reindexing is reproducible.

#### Milvus / Indexing

This phase requires a planned index rebuild.

Add a `search_text` VARCHAR field to the Milvus document collection and use it for sparse/BM25 matching. Dense embeddings should still represent the original chunk content, not the enriched text, so semantic ranking does not drift away from source evidence.

Retrieval behavior:

```text
dense search: content embedding
sparse/BM25 search: search_text
rerank: original content
prompt: original content or small-to-big expanded source content
citations: original anchor chunk
```

#### Implementation

**新文件**:
- `backend/app/rag/chunking/enrichment.py`
  - `extract_keywords(content: str, section_title: str) -> list[str]`
  - `extract_structured_tags(content: str, section_title: str) -> list[str]`
  - `build_search_text(chunk: dict) -> str`
  - `enrich_chunks(chunks: list[dict]) -> list[dict]`

**修改**: `backend/app/rag/ingestion/graph.py`
- 新节点 `enrich_chunks` 插入在 `chunk` 和 `embed_and_save` 之间
- Graph edge: `chunk → enrich_chunks → embed_and_save`

**修改**: `backend/app/rag/ingestion/config.py`
- `chunk_enrichment_enabled: bool = True`
- `chunk_enrichment_profile: str = "enterprise_policy"`

**修改**: Milvus schema / row mapping
- Add `search_text`, `keywords`, `structured_tags`
- Query output should remain schema-aware for old collections
- Existing collections are not auto-dropped; admin must reindex/reingest

#### Frontend

**修改**: `frontend/src/components/documents/DocumentDetailView.vue`
- chunk 表可显示 keywords/tags as technical metadata
- Retrieval test can show matched tags only in debug/details, not as a primary user-facing concept

#### 不做

- 不用 LLM 生成关键词（P1 纯规则）
- 不把 generated terms 注入 `content`
- 不让 LLM 引用 `search_text`
- 不做自动 destructive migration
- 不用这个替代 Doc2Query；Doc2Query remains a later recall bridge phase

#### 验证

1. `pytest backend/tests/unit/ -v`
2. 重新 ingest demo 文档，确认 `chunks.json` 包含 `keywords`、`structured_tags`、`search_text`
3. 确认 Milvus collection schema 包含 `search_text`
4. retrieval-test 运行 `recall_agg_001` 原问题，确认命中：
   - `12_年度培训计划_2026 > 五、外部培训管理`
   - `08_供应商管理制度 > 付款管理`
5. 确认 citations 仍指向 source chunk，而不是 enrichment text
6. 对比有/无 enrichment 的 Hit@5、Hit@10、Citation Hit Rate

---

## Phase 10: Tag Governance And UI Exposure

Goal: turn Phase 9 enrichment signals into a controlled tag system. Phase 9 generates retrieval signals. Phase 10 decides which signals are trusted tags, how many are allowed, where they are shown, and how quality is measured.

This phase should not add more extraction rules first. It should reduce noise and make tags governable.

### Product Research Notes

Mature search and knowledge-base systems usually separate metadata/facets from free-form keywords:

- Azure AI Search models fields explicitly as `searchable`, `filterable`, `facetable`, `retrievable`, and sortable. Search behavior and UI exposure are field-level decisions, not automatic output of an extractor.
- Amazon Kendra treats document fields/attributes as filter, facet, display, and relevance-tuning signals.
- Google Gemini Enterprise / Discovery Engine uses structured metadata for filters and recommends evaluating search quality after enabling filters.
- Pinecone treats metadata as flat JSON used for filtering; searches without metadata filters do not use metadata to narrow results.
- Weaviate creates separate inverted indexes per property and per index type, so enabling searchable/filterable properties has storage and indexing cost.
- Azure Key Phrase Extraction returns key phrases ordered by importance, but these are enrichment outputs, not necessarily user-facing tags.
- Algolia warns that unique/high-cardinality identifiers are bad facets and that facet/filter choices affect performance.

Implication for this project:

```text
structured_tags = controlled metadata/facet/debug signal
keywords        = retrieval enrichment/search_text signal
```

Do not display all keywords as primary UI tags.

### Tag Taxonomy

Define a controlled enum for `structured_tags`. P1 examples:

```text
amount_threshold
approval_rule
training_budget
deadline_rule
payment_rule
reimbursement_rule
procurement_rule
budget_rule
```

Rules:

- `structured_tags` must come from a whitelist.
- Each tag needs a short Chinese label, description, and evidence rule.
- Each tag needs an explicit priority. When more than 4 tags match one chunk, priority decides which tags are kept.
- Tags should be domain/profile aware. `enterprise_policy` tags should not be assumed useful for academic papers or generic corpora.
- Unknown extracted phrases must stay in `keywords`, not be promoted to `structured_tags`.

### Scope Levels

Support three scopes, but implement chunk scope first:

```text
document_tags:
  coarse classification, ingestion profile selection, admin filtering

section_tags:
  future section probe / long-document routing

chunk_tags:
  retrieval explanation, debug, and optional filtering
```

Tag scope should be explicit in stored artifacts:

```json
{
  "scope": "chunk",
  "structured_tags": ["amount_threshold", "approval_rule"],
  "keywords": ["VP审批", "10,000元", "外部培训管理"]
}
```

### Quantity Policy

Default limits:

```text
structured_tags per chunk: 0-3 visible, hard cap 4
keywords per chunk: 3-8 useful, hard cap 10
UI visible tags: structured_tags only, max 3 + overflow count
keywords UI: tooltip, technical details, or debug drawer only
```

Rationale:

- `structured_tags` are for controlled interpretation.
- `keywords` are for recall and diagnostics.
- Showing too many keywords makes the UI noisy and implies false precision.

### Quality Gates

Each structured tag needs a deterministic evidence rule:

```text
amount_threshold:
  amount expression + threshold term

approval_rule:
  approval/signature/review term + role/person/org term

deadline_rule:
  date/duration expression + action/requirement term
```

Quality checks:

- Unit tests for every tag rule.
- Negative tests for nearby but invalid matches.
- Golden Set slice comparing Hit@5, Hit@10, and Citation Hit Rate with tags/search_text enabled.
- Tag distribution report after ingestion:
  - top tags
  - chunks with zero tags
  - chunks with too many keywords
  - high-cardinality keywords
  - tags by document/entity/source type

### UI Policy

User-facing pages:

- Retrieval Test Top Chunks: show only `structured_tags`, max 3, overflow as `+N`.
- Query Stats / hit drawer: show `structured_tags`; `keywords` inside technical details.
- Document Detail chunk list: show `structured_tags` as optional technical metadata, not as the main content.
- Chat citations: do not show tags by default.

Admin/debug pages:

- Show full `structured_tags`, `keywords`, `search_text` length, and `enrichment_profile`.
- Add filters by tag only after tag quality is stable.

### Implementation Plan

#### Step Breakdown

10.1 Registry + Backend Validation
- Add built-in `structured_tags` registry.
- Validate enrichment output through the registry.
- Drop or downgrade unknown tags.
- Add caps for `structured_tags` and `keywords`.
- Tests: whitelist, labels, unknown tags, disabled/default behavior, caps.

10.2 UI Display Convergence
- Retrieval Test Top Chunks shows only `structured_tags`.
- Move `keywords` to tooltip/details/debug output.
- Query Stats hit drawer uses the same display policy.
- Tests: frontend build.

10.3 Admin Override API
- Add SQLite admin override table.
- Add list/update/reset API.
- Only allow label, description, enabled, and UI-visible edits.
- Return `reindex_required` when changes affect ingestion output.

10.4 Tag Governance UI
- Add `标签治理` page under System Settings or Quality Center.
- Show tag key, label, scope, profile, enabled, UI-visible, counts, and actions.
- Support edit and preview only; no free create/delete.

10.5 Preview + Metrics
- Preview tag extraction from pasted text or selected document without writing to storage.
- Add ingestion tag distribution report.
- Run Golden Set recall slice before/after governance changes.

#### Detailed Tasks

1. Add Tag Registry.
   - Backend defines built-in `structured_tags`.
   - Registry fields: `tag_key`, Chinese label, description, priority, scope, profile, default enabled, default UI visible.
   - P1 registry only includes tags currently emitted by extraction rules. Future tags are added when their extraction rules exist.
   - Built-in tags cannot be deleted and `tag_key` cannot be edited.

2. Add Admin Tag Settings.
   - Store admin overrides in SQLite.
   - Admin can edit Chinese label, description, enabled state, and UI-visible state.
   - Admin cannot freely create/delete tags in P1.
   - Disabling a tag affects new enrichment, UI, filtering, and search_text expansion. Historical chunk artifacts can remain unchanged until reindex.

3. Wire enrichment through registry.
   - Enrichment rules may only emit registered `structured_tags`.
   - Unknown rule outputs are dropped or downgraded to `keywords`.
   - Disabled tags are excluded from new enrichment output.
   - Settings changes should clearly show `reindex required`.

4. Add caps and UI exposure rules.
   - Add caps for visible tags and stored keywords.
   - Update Retrieval Test table to show only `structured_tags` in the primary `标签` column.
   - Move `keywords` to tooltip/details/debug output.
   - Add a shared frontend/backend label map for `structured_tags`.

5. Add Preview.
   - Admin selects a document or pastes text.
   - Backend runs tag rules without writing to storage.
   - Return matched tags, evidence snippets, keywords, and `search_text` summary.
   - Preview is required before making tag rule changes user-visible in later versions.

6. Add Metrics.
   - Add ingestion tag distribution report:
     - top tags
     - chunks per tag
     - documents per tag
     - zero-tag chunks
     - too-many-keywords chunks
     - high-cardinality keywords
     - tags by document/entity/source type
   - UI shows summary metrics; detailed JSON can stay debug/download only.

7. Add Frontend Admin UI.
   - Place under System Settings or Quality Center as `标签治理`.
   - Table columns: label, tag key, scope, profile, enabled, UI visible, chunk count, actions.
   - Actions: edit display fields, preview.
   - No free create/delete controls in P1.

8. Add tests and validation.
   - Unit tests for registry validation, disabled tags, caps, and negative extraction cases.
   - API tests for admin override behavior.
   - Run Golden Set recall slice before/after tag governance changes.

### Not Doing

- No free-form LLM-generated structured tags.
- No admin free-create/free-delete tags in P1.
- No manual per-chunk tagging.
- No query-time automatic promotion from keyword to tag.
- No user-facing keyword cloud.
- No tag filters until tag quality metrics are stable.
- No universal domain tag system in P1; start with `enterprise_policy`.

---

## Phase 11A: Section Probe Retrieval Experiment

Goal: test a coarse-to-fine retrieval path for long documents and long sections. Section probes should help when a whole section is relevant to the query, but individual chunks are too local or too weakly worded to be retrieved directly.

This is an experiment after Phase 9 and Phase 10, not a default path. Enable it only for `recall` and compare against the challenge set before making it permanent.

### Design

#### Probe Granularity

Use section-level probes only. Do not start with document-level probes.

Document summaries are usually too broad and can pull unrelated chunks into the candidate set. Section probes are closer to the final source chunks while still carrying more context than one chunk.

Probe text should be structured rather than a free-form summary:

```text
section_title:
main_topics:
entities:
policy_terms:
amounts:
dates:
roles:
procedures:
aliases:
```

#### Query Flow

```text
recall flavor:
  search(original_query) -> source chunks
  section_probe_search(original_query) -> top sections
  scoped_chunk_search(query, matched_sections) -> source chunks only
  rrf_fusion
  rerank(source chunk content)
  context_expand
  build_prompt
```

Probes never enter the final context directly. They only select candidate document/section scopes. Citations always point to source chunks.

#### Risk Controls

- Max matched probe sections: 3
- Max scoped chunks per section: 4
- Max probe-derived chunks before RRF: 8-12
- Drop probe path if probe score is below threshold
- Drop scoped chunks if their score is below threshold
- Trace must show probe section, probe score, scoped query count, and final source chunks

#### Risks

- Summary/probe text can be too broad and increase noise.
- Probe text can miss the important detail and still fail recall.
- Additional retrieval layer increases latency.
- Trace becomes more complex.

Mitigation: keep it recall-only, low-weight, capped, and disabled by default until eval shows value.

#### Implementation Files

**New**:
- `backend/app/rag/ingestion/section_probe.py`
- `backend/app/rag/vectorstores/section_probe_milvus.py`
- `backend/app/rag/query/section_probe_search.py`
- `backend/tests/unit/test_section_probe.py`

**Modify**:
- `backend/app/rag/ingestion/graph.py`
- `backend/app/rag/ingestion/config.py`
- `backend/app/rag/query/config.py`
- `backend/app/rag/query/planner.py`
- `backend/app/rag/query/rrf_fusion.py`
- `backend/app/rag/query/graph.py`
- `backend/app/api/query_chat.py`
- `backend/app/services/retrieval_test_service.py`

#### Validation

1. Run recall slice with probe off/on.
2. Confirm improved Hit@10/Citation Hit Rate for long-section cases.
3. Confirm p95 latency remains acceptable.
4. Confirm probe text is not shown as citation evidence.
5. Confirm `balanced`, `exact`, and `discovery` do not trigger probe search.

---

## Phase 11B: Doc2Query — Chunk Question Generation

Goal: generate 3-5 answerable questions per text chunk, index in a companion Milvus collection, and use as a recall bridge during retrieval. Only active for `recall` flavor initially.

Positioning after Phase 9:

- Phase 9 fixes deterministic lexical gaps: tags, amount phrases, approval roles, aliases, and `search_text`.
- Phase 11A tests whether section probes solve long-document recall before adding generated questions per chunk.
- Phase 11B fixes semantic question-form gaps: users ask a natural question that the original chunk can answer, but neither exact keywords, rule-based tags, nor section probes cover it.
- Do not use Doc2Query as the first fix for every missed recall case. It adds LLM cost, generated-content QA, another collection, and more ingestion complexity.

Doc2Query should be enabled only after Phase 9 and the Section Probe experiment are measured against the challenge set and still leave recall-heavy cases failing.

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
