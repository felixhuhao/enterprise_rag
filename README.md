# Enterprise RAG Platform

> Production-grade document intelligence: ingest PDF/Markdown/ZIP, hybrid retrieval with rerank, streaming Q&A with citations, and built-in observability.

## Quick Start (Docker)

**Prerequisites**: Docker Desktop running, local dense embedding model files (tested with `BAAI/bge-m3`), a [DashScope API key](https://dashscope.console.aliyun.com/) for LLM/image descriptions, and optionally a [MinerU token](https://mineru.net/) for PDF parsing.

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
  │ SQLite│          │  Milvus  │        │  Local   │        │ DashScope│
  │ state │          │ vectors  │        │embedding │        │  + MinerU│
  └───────┘          └──────────┘        └──────────┘        └──────────┘
```

### Ingestion Pipeline

```
upload → parse (MinerU / Markdown) → image-to-text → chunk → embed → Milvus
```

### Query Pipeline

```
entity_confirm → rewrite → [dense+sparse search, HyDE] → RRF → table_expand → rerank → generate → citations
```

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, LangGraph, SQLite, Pydantic |
| Vector Store | Milvus (dense + BM25 sparse) |
| Embedding | Local dense embedding model (tested with BAAI/bge-m3) |
| LLM | Qwen-Plus (DashScope) |
| PDF Parsing | MinerU Online API |
| Image-to-Text | Qwen-VL |
| Frontend | Vue 3, TypeScript, Arco Design Vue |

## Features

- **Multi-format ingestion** — PDF (via MinerU), Markdown, Markdown ZIP
- **Text-first multimodal** — images described and indexed as text, no separate VL embedding space
- **Table-aware chunking** — small tables as full chunks, large tables as row groups
- **Hybrid retrieval** — dense + BM25 sparse, RRF fusion, HyDE, LLM rerank
- **Retrieval testing** — run recall and rerank without generation, with strategy and trace summary
- **Streaming answers with citations** — numbered citations, image evidence, source validation
- **Observability** — per-query trace, rerank scores, latency breakdown, error classification
- **Evaluation** — golden set runner with rule / LLM-judge / no-answer scoring

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
│   │   │   ├── chunking/         # markdown + table chunker
│   │   │   ├── embeddings/       # local dense embedding client
│   │   │   ├── ingestion/        # LangGraph ingestion workflow
│   │   │   ├── parsing/          # MinerU, Markdown, image describer, ZIP
│   │   │   ├── query/            # search, fusion, rerank, prompt, citations
│   │   │   └── vectorstores/     # Milvus collection management
│   │   └── services/             # document, chat history, query stats
│   ├── scripts/
│   │   ├── seed_demo.py          # idempotent demo data seeding
│   │   └── eval_golden_set.py    # golden set evaluation runner
│   └── tests/
├── frontend/
│   └── src/
│       ├── api/
│       ├── components/           # query-chat, documents, evaluate, settings
│       ├── stores/
│       └── styles/
└── data/
    ├── enterprise_docs/           # Fast Markdown demo corpus + .entity file
    ├── enterprise_docs_v1.jsonl   # Markdown demo golden set
    └── stock reports/             # Legacy PDF demo corpus
```

## Configuration

Required:

| Variable | Description |
|---|---|
| `EMBEDDING_MODEL_HOST_PATH` | Host path to the local embedding model for Docker volume mount, e.g. `D:/Models/BAAI/bge-m3` |
| `EMBEDDING_MODEL_PATH` | Runtime embedding model path. Docker uses `/models/embedding`; local dev can use `D:\Models\BAAI\bge-m3` |
| `DEEPSEEK_API_KEY` | DeepSeek API key for chat, HyDE, rerank |
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
python -m pytest tests/unit -v

# Frontend
cd frontend
npm run build
```

## Documentation

- [Architecture](docs/architecture.md) — system diagrams and data flow details
- [Evaluation](docs/evaluation.md) — golden set design, scoring, and baseline results
