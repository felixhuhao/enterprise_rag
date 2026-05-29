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
small_to_big_max_chars = 2400
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
