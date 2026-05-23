# Architecture

## System Overview

```
                          ┌─────────────────────────────────────────┐
                          │           Vue 3 Frontend                │
                          │  Query Chat · Documents · Evaluate      │
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
│  │(LangGraph)│ │(LangGraph)│  │ Service  │                        │
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
   │ SQLite  │   │  Milvus   │   │ DashScope  │
   │ (state) │   │ (vectors) │   │ + MinerU   │
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
                  │    Embed     │  text-embedding-v4 → 1024-dim vectors
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

## Query Pipeline

Each user query runs through a LangGraph pipeline that handles entity routing, retrieval, and generation.

```
                    User Query
                        │
                        ▼
               ┌─────────────────┐
               │ Entity Confirm  │  detect entity, confirm or fallback
               └────────┬────────┘
                        ▼
               ┌─────────────────┐
               │  Query Rewrite  │  optimize for retrieval
               └────────┬────────┘
                        │
          ┌─────────────┼─────────────┐
          ▼                           ▼
  ┌───────────────┐          ┌───────────────┐
  │ Dense+Sparse  │          │   HyDE Search │
  │    Search     │          │ (hypothetical │
  │ (Milvus hybrid│          │   document)   │
  │  + BM25 field)│          └───────┬───────┘
  └───────┬───────┘                  │
          └─────────────┼─────────────┘
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
                        │
                        ▼
              Response + Citations
              + Trace + Query Stats
```

### Search Modes

The pipeline adapts based on entity detection and search results:

| Mode | When |
|---|---|
| `entity_filtered` | Entity detected, enough filtered results |
| `entity_filtered_hyde_fallback` | Entity detected, filtered results insufficient, HyDE used |
| `no_entity` | No entity detected, broad search |
| `no_entity_hyde_fallback` | No entity, initial results insufficient |

## Observability

Every query records structured stats for monitoring and evaluation.

### Per-Query Trace (SSE)

| Field | Description |
|---|---|
| `search_mode` | Which retrieval mode was used |
| `rewritten_query` | Optimized query text |
| `entity_filter` | Entity match result |
| `search_results` | Raw retrieval hit count and scores |
| `rerank_scores` | Top and average rerank scores |
| `selected_citations` | Final citation list with source metadata |
| `latency_ms` | Per-stage timing breakdown |

### Aggregate Stats

The Evaluate page shows:

| Metric | Source |
|---|---|
| Total queries | Count across all statuses |
| Failure rate | `(search_failed + llm_failed + client_aborted) / total` |
| Avg rerank score | Mean rerank score across successful queries |
| Avg result count | Mean retrieved documents per query |
| Fallback count/ratio | How often entity filter fell back to broad search |

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

5. **Entity-aware retrieval with graceful fallback** — Entity filter narrows results when possible, falls back to broad search when filtered results are insufficient.
