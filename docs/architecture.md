# Architecture

## System Overview

```
                          ┌─────────────────────────────────────────┐
                          │           Vue 3 Frontend                │
                          │ Query Chat · Documents · Quality Center │
                          └────────────────┬────────────────────────┘
                                           │ HTTP / SSE
                                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        FastAPI Backend                               │
│                                                                      │
│  ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │ Documents│  │Query Chat │  │  Query   │  │    Settings      │   │
│  │   API    │  │   SSE API │  │  Stats   │  │    API           │   │
│  └────┬─────┘  └─────┬─────┘  └────┬─────┘  └──────────────────┘   │
│       │              │              │                                  │
│  ┌────▼─────┐  ┌─────▼─────┐  ┌───▼──────┐                        │
│  │Ingestion │  │  Query    │  │  Query   │                        │
│  │ Workflow │  │ Pipeline  │  │  Stats   │                        │
│  │(LangGraph)│ │ Planner   │  │ Service  │                        │
│  └────┬─────┘  └─────┬─────┘  └──────────┘                        │
│       │              │                                              │
│  ┌────▼──────────────▼──────────────────────┐                      │
│  │              Shared Services              │                      │
│  │  Embeddings · Milvus Client · LLM Client │                      │
│  └────┬──────────────┬──────────────────────┘                      │
│       │              │                                              │
└───────┼──────────────┼──────────────────────────────────────────────┘
        │              │
   ┌────▼────┐   ┌─────▼─────┐   ┌───────────┐
   │ SQLite  │   │  Milvus   │   │ LLM APIs  │
   │ (state) │   │ (vectors) │   │ + MinerU  │
   └─────────┘   └───────────┘   └─────────────┘
```

## Ingestion Pipeline

Documents flow through a LangGraph state machine. Each node updates document status in SQLite, enabling progress tracking and retry.

```
                          Upload
                            │
                            ▼
                    ┌──────────────┐
                    │   Validate   │  file type, magic bytes, size
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         ┌────────┐  ┌─────────┐  ┌─────────┐
         │ MinerU │  │Markdown │  │  ZIP    │
         │ Parser │  │ Loader  │  │ Parser  │
         └───┬────┘  └────┬────┘  └────┬────┘
             │            │            │
             └────────────┼────────────┘
                          ▼
                  ┌──────────────┐
                  │ Image-to-Text│  VL model describes images/charts
                  └──────┬───────┘
                         ▼
                  ┌──────────────┐
                  │   Normalize  │  clean markdown, merge sections
                  └──────┬───────┘
                         ▼
                  ┌──────────────┐
                  │    Chunk     │  text chunks + table chunks
                  └──────┬───────┘
                         ▼
                  ┌──────────────┐
                  │   Enrich     │  keywords, structured tags, search_text
                  │ Search Meta  │
                  └──────┬───────┘
                         ▼
                  ┌──────────────┐
                  │    Embed     │  local dense embedding → 1024-dim vectors
                  └──────┬───────┘
                         ▼
                  ┌──────────────┐
                  │   Save to    │  upsert chunks into Milvus
                  │    Milvus    │  update SQLite status → completed
                  └──────────────┘
```

### Chunking Strategy

| Content Type | Strategy |
|---|---|
| Text paragraphs | Split by headers + sentence boundaries, ~500 chars |
| Small tables | `table_summary` + `table_full` as a single chunk |
| Large tables | `table_summary` + row groups, each with `raw_table_path` for traceability |
| Image descriptions | Injected into adjacent text chunks before splitting |
| Search metadata | Deterministic keywords, structured tags, and sparse `search_text` |

## Query Pipeline

Each user query first resolves a `QueryPlan`, then runs the appropriate retrieval path. The public controls are:

```text
retrieval_flavor = balanced | exact | recall | discovery
strict_evidence = true | false
```

Users see the Chinese labels: 标准问答, 精确查找, 全面查找, 关联查找.

```
                    User Query
                        │
                        ▼
               ┌─────────────────┐
               │ Entity Confirm  │  detect entity, confirm or fallback
               └────────┬────────┘
                        ▼
               ┌─────────────────┐
               │   Query Plan    │  flavor, strictness, fallback policy, budget
               └────────┬────────┘
                        ▼
               ┌─────────────────┐
               │  Query Rewrite  │  optimize for retrieval
               └────────┬────────┘
                        │
          ┌─────────────┼────────────────────┬─────────────────┐
          ▼             ▼                    ▼                 ▼
  ┌───────────────┐ ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
  │ Dense+Sparse  │ │   HyDE Search │ │ Query Expand  │ │ Multi-Hop     │
  │ Search        │ │ balanced only │ │ recall only   │ │ discovery only│
  └───────┬───────┘ └───────┬───────┘ └───────┬───────┘ └───────┬───────┘
          └─────────────────┼─────────────────┼─────────────────┘
                        ▼
               ┌─────────────────┐
               │   RRF Fusion    │  merge ranked lists
               └────────┬────────┘
                        ▼
               ┌─────────────────┐
               │  Table Expand   │  expand table chunks with context
               └────────┬────────┘
                        ▼
               ┌─────────────────┐
               │    Rerank       │  LLM cross-encoder rerank
               └────────┬────────┘
                        ▼
               ┌─────────────────┐
               │ Diversify       │  reduce duplicate evidence for recall/discovery/synthesis
               │ Context         │
               └────────┬────────┘
                        ▼
               ┌─────────────────┐
               │ Context Expand  │  same-section neighbor chunks
               └────────┬────────┘
                        ▼
               ┌─────────────────┐
               │ Build Prompt    │  assemble context + citations
               └────────┬────────┘
                        ▼
               ┌─────────────────┐
               │    Generate     │  streaming LLM answer (SSE)
               └────────┬────────┘
                        ▼
               ┌─────────────────┐
               │    Validate     │  verify citations against sources
               │   Citations     │
               └────────┬────────┘
                        ▼
               ┌─────────────────┐
               │ Groundedness    │  optional support diagnostics
               └────────┬────────┘
                        │
                        ▼
              Response + Citations
              + Trace + Query Stats
```

### Retrieval Flavors

The planner normalizes user intent into one of four retrieval flavors:

| Flavor | UI Label | Retrieval Behavior |
|---|---|
| `balanced` | 标准问答 | Hybrid search, optional HyDE, RRF, rerank, context expansion |
| `exact` | 精确查找 | Smaller budget, no HyDE/query expansion, no entity fallback |
| `recall` | 全面查找 | Query expansion, parallel searches, RRF, rerank |
| `discovery` | 关联查找 | Bounded multi-hop retrieval with discovered entities or people |

`strict_evidence` is an evidence policy layered on top of retrieval. It blocks risky fallback and instructs the answer prompt to refuse unsupported facts.

### Entity And Alias Routing

Entity routing uses canonical entity names plus admin-managed aliases. Alias matches normalize to the canonical entity. Ambiguous aliases are recorded in trace and do not force a single-entity filter.

Fallback from entity-filtered search to broader search is policy-driven:

| Case | Behavior |
|---|---|
| Balanced / recall weak entity evidence | May widen scope and records `fallback_info.used` |
| Exact / strict evidence | Blocks entity fallback and records `fallback_info.blocked` |
| Multi-entity | Searches per entity instead of one global fallback |

## Observability

Every query records structured stats for monitoring and evaluation.

### Per-Query Trace (SSE)

| Field | Description |
|---|---|
| `search_mode` | Which retrieval mode was used |
| `rewritten_query` | Optimized query text |
| `entity_filter` | Entity match result |
| `retrieval_flavor` | Resolved strategy |
| `strict_evidence` | Evidence policy |
| `expanded_queries` | Recall query expansion variants |
| `fallback_info` | Whether entity scope widened or was blocked |
| `context_expand_ms` | Small-to-big context expansion timing |
| `search_results` | Raw retrieval hit count and scores |
| `rerank_scores` | Top and average rerank scores |
| `selected_citations` | Final citation list with source metadata |
| `latency_ms` | Per-stage timing breakdown |

### Aggregate Stats

The Quality Center shows:

| Metric | Source |
|---|---|
| Total queries | Count across all statuses |
| Failure rate | `(search_failed + llm_failed + client_aborted) / total` |
| Avg rerank score | Mean rerank score across successful queries |
| Avg result count | Mean retrieved documents per query |
| P95 latency | 95th percentile total query latency |
| Fallback count/ratio | How often entity filter widened to broader search |
| Per-flavor breakdown | Count, success rate, results, rerank score, and p95 latency by flavor |

### Error Classification

| Code | Meaning | User Hint |
|---|---|---|
| `MINERU_UNAVAILABLE` | MinerU API unreachable | "PDF parsing service unavailable" |
| `MINERU_PARSE_FAILED` | MinerU returned error | "PDF parsing failed" |
| `EMBEDDING_FAILED` | Embedding API error | "Embedding service error" |
| `MILVUS_ERROR` | Vector store error | "Storage service error" |
| `LLM_GENERATION_FAILED` | LLM API error during answer generation | "Answer generation failed" |
| `CLIENT_ABORTED` | User disconnected mid-stream | — |

## Data Flow

```
┌──────────┐    upload     ┌─────────┐    parse     ┌──────────┐
│   File   │──────────────►│ SQLite  │─────────────►│ Markdown │
│ (PDF/MD) │               │ (state) │              │  + Assets│
└──────────┘               └─────────┘              └────┬─────┘
                                                         │ chunk + embed
                                                         ▼
                                                  ┌──────────────┐
                                                  │    Milvus    │
                                                  │  (chunks +   │
                                                  │   embeddings)│
                                                  └──────┬───────┘
                                                         │ search
                                                         ▼
User ──query──► Query Pipeline ──SSE──► Answer + Citations + Trace
                        │
                        ▼
                  ┌──────────┐
                  │ SQLite   │
                  │(q stats) │
                  └──────────┘
```

## Key Design Decisions

1. **Text-first multimodal** — Images are converted to text descriptions during ingestion, indexed with the same text embedding model. No separate VL embedding space, no query-time vision calls.

2. **SQLite for state, Milvus for vectors** — Application state (documents, stats, history) in SQLite for simplicity. Vectors and hybrid search in Milvus for scalability.

3. **LangGraph workflows** — Both ingestion and query use LangGraph state machines, making the pipeline inspectable, debuggable, and easy to add nodes.

4. **Idempotent ingestion** — Each document has a unique ID. Re-processing (retry) deletes old chunks before inserting new ones. Seed script is safe to re-run.

5. **Entity-aware retrieval with explicit fallback** — Entity filters narrow results when possible. Fallback is policy-driven and visible in prompt, trace, and UI.

6. **Stable chunk keys** — Source chunks have durable `chunk_key` values for citations, stats, feedback, and document-detail navigation. Milvus auto ids remain technical fields.

7. **Evaluation as product workflow** — Feedback can become draft baseline cases. Admins can edit, enable, disable, and run the baseline set from the Quality Center.
