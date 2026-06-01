# Enterprise RAG Platform

> Production-grade document intelligence: ingest PDF/Markdown/ZIP, strategy-aware retrieval, streaming Q&A with citations, and built-in quality evaluation.

## Quick Start (Docker)

**Prerequisites**: Docker Desktop running, local dense embedding model files (tested with `BAAI/bge-m3`), a DeepSeek-compatible chat API key, a Zhipu image-description API key, and optionally a [MinerU token](https://mineru.net/) for PDF parsing.

```bash
# 1. Configure
cp .env.example .env
# Edit .env — set EMBEDDING_MODEL_HOST_PATH, DEEPSEEK_API_KEY, ZHIPU_API_KEY, and MINERU_API_TOKEN (for PDF)

# 2. Launch
docker compose up -d --build

# 3. Seed demo data (fast Markdown enterprise corpus by default)
docker compose exec backend python scripts/seed_demo.py

# 4. Open
# http://localhost:5173  —  default token: enterprise-rag-dev-token
```

Milvus data persists in `./data/milvus`. Re-run `seed_demo.py` anytime — it skips already-completed documents. The default demo corpus is `data/enterprise_docs`; the legacy PDF stock-report demo is still available with `--data-dir "../data/stock reports"` and requires MinerU.

If you change embedding models, reset the Milvus collection and re-process documents:

```bash
docker compose exec backend python scripts/reset_milvus_collection.py
docker compose exec backend python scripts/seed_demo.py
```

## Local Development

Use two separate `.env` files:

- `backend/.env` — backend config (copy from `.env.example`)
- Frontend reads `VITE_API_TARGET` from `frontend/.env` (defaults to `http://localhost:8010`)

For local backend development on Windows, set:

```env
EMBEDDING_MODEL_PATH=D:\Models\BAAI\bge-m3
```

```bash
# Terminal 1 — Backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload

# Terminal 2 — Frontend
cd frontend
npm install
npm run dev
```

Start a local Milvus instance first (or point `MILVUS_URI` to an existing one).

## Demo Scope

The default demo corpus is a curated enterprise Markdown knowledge base under `data/enterprise_docs`.
It covers HR, reimbursement, procurement, information security, API specs, incident runbooks, SLA, project management, meeting notes, and two demo entities: `星辰科技` and `远景能源`.

Useful demo queries:

| Scenario | Query | Suggested Strategy |
|---|---|---|
| Clause / amount lookup | `星辰科技的住宿标准是多少？` | 精确查找 |
| Vague recall | `电脑丢了应该怎么处理？` | 全面查找 |
| Cross-document synthesis | `星辰科技的安全事件报告和运维故障响应有什么关联和区别？` | 标准问答 |
| Multi-hop discovery | `API v1什么时候下线？迁移指南由谁负责？这个人还负责什么工作？` | 关联查找 |
| Strict evidence / missing fact | `星辰科技的API日调用量上限是多少？` with “仅基于资料回答” enabled; expected to cite per-minute limits and refuse a daily cap | 标准问答 |

## Retrieval Strategies

The UI exposes user intent, not low-level switches:

| Strategy | Internal Flavor | Use For | Main Behavior |
|---|---|---|---|
| 标准问答 | `balanced` | Daily Q&A and synthesis | Hybrid search + optional HyDE + RRF + rerank + context expansion |
| 精确查找 | `exact` | Clauses, numbers, standards, source lookup | Smaller budget, HyDE off, entity fallback disabled |
| 全面查找 | `recall` | Vague wording or synonym-heavy questions | Query expansion, parallel search, RRF merge, rerank |
| 关联查找 | `discovery` | Questions that must discover related people/entities first | Constrained multi-hop retrieval with traceable hops |

`strict_evidence` is independent from retrieval flavor. When enabled, the answer must stay conservative and refuse unsupported facts instead of inferring them.

## Architecture

```
┌──────────┐     SSE      ┌──────────┐
│  Vue 3   │◄────────────►│  FastAPI │
│ Frontend │              │ Backend  │
└──────────┘              └────┬─────┘
      │  ┌───────────────────┼──────────────────┐
      │  │                   │                  │
      ▼  ▼                   ▼                  ▼
  ┌───────┐          ┌──────────┐        ┌──────────┐        ┌──────────┐
  │ SQLite│          │  Milvus  │        │  Local   │        │ LLM APIs│
  │ state │          │ vectors  │        │embedding │        │ + MinerU│
  └───────┘          └──────────┘        └──────────┘        └──────────┘
```

### Ingestion Pipeline

```
upload → parse (MinerU / Markdown / ZIP) → image-to-text → chunk
  → enrich search metadata → embed → Milvus
```

### Query Pipeline

```
entity_confirm → query_plan → rewrite
  → direct search / query expansion / multi-hop discovery
  → RRF → table_expand → rerank → diversify_context
  → context_expand → build_prompt → generate → validate_citations → groundedness
```

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, LangGraph, SQLite, Pydantic |
| Vector Store | Milvus (dense + BM25 sparse) |
| Embedding | Local dense embedding model (tested with BAAI/bge-m3) |
| LLM | DeepSeek-compatible chat API |
| PDF Parsing | MinerU Online API |
| Image-to-Text | Zhipu GLM-4.6V-compatible API |
| Frontend | Vue 3, TypeScript, Arco Design Vue |

## Features

- **Multi-format ingestion** — PDF (via MinerU), Markdown, Markdown ZIP
- **Text-first multimodal** — images described and indexed as text, no separate VL embedding space
- **Table-aware chunking** — small tables as full chunks, large tables as row groups
- **Metadata enrichment** — deterministic enterprise-policy tags and search text for better sparse recall
- **Strategy-aware retrieval** — balanced, exact, recall, and discovery flavors with resolved budgets
- **Hybrid retrieval** — dense + BM25 sparse, RRF fusion, HyDE, query expansion, multi-hop discovery, LLM rerank
- **Small-to-big context** — final anchor chunks can include neighboring chunks from the same section
- **Retrieval testing** — inspect Top K chunks, trace, budgets, expansion queries, tags, and rerank scores without answer generation
- **Streaming answers with citations** — numbered citations, image evidence, source validation
- **Observability** — per-query trace, rerank scores, latency breakdown, error classification
- **Quality center** — query records, answer feedback, stats by retrieval flavor, and baseline evaluation
- **Evaluation** — baseline test set runner with rule / LLM-judge / no-answer scoring
- **Admin tuning** — entity aliases, runtime settings, retrieval strategy tuning, and structured tag controls

## Project Structure

```
enterprise_rag/
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── app/
│   │   ├── api/                  # REST endpoints: documents, query, stats, settings
│   │   ├── core/                 # database, config, runtime settings
│   │   ├── rag/
│   │   │   ├── chunking/         # markdown/table chunker + enrichment tags
│   │   │   ├── embeddings/       # local dense embedding client
│   │   │   ├── ingestion/        # LangGraph ingestion workflow
│   │   │   ├── parsing/          # MinerU, Markdown, image describer, ZIP
│   │   │   ├── query/            # search, fusion, rerank, prompt, citations
│   │   │   └── vectorstores/     # Milvus collection management
│   │   └── services/             # document, chat history, query stats
│   ├── scripts/
│   │   ├── seed_demo.py          # idempotent demo data seeding
│   │   └── eval_golden_set.py    # baseline evaluation runner
│   └── tests/
├── frontend/
│   └── src/
│       ├── api/
│       ├── components/           # query-chat, documents, evaluate, settings
│       ├── stores/
│       └── styles/
└── data/
    ├── enterprise_docs/           # Fast Markdown demo corpus + .entity file
    ├── challenge_golden_set_v1.jsonl # Enterprise baseline test set
    └── stock reports/             # Legacy PDF demo corpus
```

## Configuration

Required:

| Variable | Description |
|---|---|
| `EMBEDDING_MODEL_HOST_PATH` | Host path to the local embedding model for Docker volume mount, e.g. `D:/Models/BAAI/bge-m3` |
| `EMBEDDING_MODEL_PATH` | Runtime embedding model path. Docker uses `/models/embedding`; local dev can use `D:\Models\BAAI\bge-m3` |
| `DEEPSEEK_API_KEY` | DeepSeek-compatible API key for chat, HyDE, query expansion, rerank, and evaluation judge |
| `ZHIPU_API_KEY` | Zhipu AI API key for image description (GLM-4.6V) |
| `API_TOKEN` | Bearer token for API auth |

Optional:

| Variable | Default | Description |
|---|---|---|
| `CHAT_MODEL` | `deepseek-v4-flash` | LLM model name |
| `EMBEDDING_MODEL_NAME` | `bge-m3` | Display name for the embedding model in diagnostics |
| `MINERU_API_TOKEN` | — | Required for PDF parsing |
| `MILVUS_URI` | `http://localhost:19530` | Milvus connection |
| `EMBEDDING_BATCH_SIZE` | `4` | Embedding batch size |
| `EMBEDDING_DEVICE` | `auto` | `auto`, `cuda`, or `cpu` |
| `IMAGE_DESCRIPTION_ENABLED` | `true` | Enable image-to-text |

Full list in `.env.example`.

## Verification

```bash
# Backend
cd backend
python -m pytest tests/unit -q

# Frontend
cd frontend
npm run build
```

## Baseline Evaluation

Run the enterprise baseline test set after retrieval, prompt, tag, or chunking changes:

```bash
cd backend
python scripts/eval_golden_set.py \
  --golden-set ../data/challenge_golden_set_v1.jsonl \
  --api-base http://127.0.0.1:8010/api \
  --judge \
  --output ../data/challenge_golden_set_v1_results.jsonl
```

The same cases can also be managed from the Quality Center. Feedback can be turned into draft baseline cases, edited, enabled/disabled, and run from the UI.

## Rebuilding The Index

Rebuild Milvus when indexed fields or chunk content change:

- embedding model or embedding dimension changes
- chunking rules change
- table chunking changes
- `search_text`, structured tag extraction, or enrichment profile changes
- parsed artifacts are regenerated

Code-only changes to rerank, prompt, budgets, query planning, evaluation scoring, frontend labels, or baseline expectations do not require rebuilding the index.

```bash
docker compose exec backend python scripts/reset_milvus_collection.py
docker compose exec backend python scripts/seed_demo.py
```

## Admin Tag Tuning

Structured tags are deterministic ingestion-time metadata used for retrieval debugging and sparse recall. Admins can:

- view registered tags and chunk distribution in System Settings
- hide tags from UI without changing retrieval behavior
- enable/disable a tag rule; disabling an indexed tag requires reprocessing documents
- preview tag extraction on pasted text or existing parsed chunks

Tags are intentionally coarse and limited. They are not a user-editable free-form taxonomy.

## Documentation

- [Architecture](docs/architecture.md) — system diagrams and data flow details
- [Evaluation](docs/evaluation.md) — baseline test set design, scoring, and UI workflow
- [Smoke Test](docs/smoke_test.md) — manual regression checklist for demo paths
