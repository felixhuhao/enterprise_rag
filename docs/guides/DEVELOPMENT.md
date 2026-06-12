# Development Guide

This guide keeps operational setup out of the project README. Use it when you need to run, seed, test, reset, or evaluate the application.

## Docker Quick Start

Prerequisites:

- Docker Engine or Docker Desktop.
- Local dense embedding model files, tested with `BAAI/bge-m3`.
- DeepSeek-compatible chat API key.
- Zhipu image-description API key.
- Optional MinerU token for PDF parsing.

```bash
cp .env.example .env
```

Edit `.env`:

```env
EMBEDDING_MODEL_HOST_PATH=/home/hao/models/BAAI/bge-m3
DEEPSEEK_API_KEY=sk-your-key
ZHIPU_API_KEY=your-zhipu-key
MINERU_API_TOKEN=
API_TOKEN=enterprise-rag-dev-token
```

Start the stack:

```bash
docker compose up -d --build
docker compose ps
```

Seed the fast Markdown enterprise corpus:

```bash
docker compose exec backend python scripts/seed_demo.py
```

Open:

```text
Frontend: http://localhost:5173
Backend health: http://localhost:8010/health
Default local token: enterprise-rag-dev-token
```

Milvus data persists in Docker named volumes (`milvus-data`, `milvus-etcd`), not in the project directory. Re-run `seed_demo.py` anytime; it skips already-completed documents.

## Docker Build Cache

The backend image contains large ML dependencies. Its Dockerfile uses a BuildKit
pip cache mount so that if the dependency layer is invalidated, downloaded
wheels can be reused instead of pulling several GB again.

The first backend dependency build after a cache reset can still be slow. Future
builds should reuse the cache unless Docker builder cache is pruned or the
requirements change substantially.

For normal code changes, prefer the development override. It bind-mounts source
files into the existing containers and enables backend auto-reload:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

After that, backend edits under `backend/app` and `backend/scripts` reload
without rebuilding. Frontend edits under `frontend/src` are served by Vite from
the mounted working tree.

Do not use `--build` for ordinary source edits. Rebuild only when dependencies
or image definitions change:

| Change | Command |
|---|---|
| Backend Python source | No rebuild; dev override reloads backend |
| Frontend source | No rebuild; dev override lets Vite serve mounted source |
| `backend/requirements.txt` or `backend/Dockerfile` | `docker compose build backend` |
| `frontend/package.json`, `frontend/package-lock.json`, or `frontend/Dockerfile` | `docker compose build frontend` |
| Compose config or env vars | `docker compose up -d` |

For frontend-only image rebuilds, avoid rebuilding backend:

```bash
docker compose build frontend
docker compose up -d --no-deps frontend
```

For backend source-only changes when Milvus is already running:

```bash
docker compose build backend
docker compose up -d --no-deps backend
```

## Local Development

Docker is the default runtime path. Local backend development is useful for linting, unit tests, and fast API iteration.

Use separate env files:

- root `.env` for Docker Compose
- `backend/.env` for backend local runs
- `frontend/.env` for frontend local runs, usually only `VITE_API_TARGET`

For local backend runs, set the runtime model path:

```env
EMBEDDING_MODEL_PATH=/home/hao/models/BAAI/bge-m3
MILVUS_URI=http://localhost:19530
```

Backend:

```bash
cd backend
python -m pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Start a local Milvus instance first, or point `MILVUS_URI` to an existing one.

## Python Environments

For lightweight development, the project venv can omit PyTorch and FlagEmbedding. It can still run Ruff, Pyright, and many unit tests.

For real local embedding, install:

```bash
python -m pip install torch FlagEmbedding
```

CUDA PyTorch is useful for ingestion and retrieval evaluation, but not required for linting or most tests. CPU works with `EMBEDDING_DEVICE=cpu`, but bge-m3 will be slower.

## Verification

Backend health:

```bash
curl -fsS http://127.0.0.1:8010/health
```

Backend unit tests:

```bash
cd backend
PYTHONPATH=. python -m pytest tests/unit -q
```

Focused local checks from the repository root:

```bash
.venv/bin/python -m ruff check backend/app backend/scripts
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/unit/test_query_state.py \
  backend/tests/unit/test_search_pipeline.py \
  backend/tests/unit/test_query_chat_retrieved_chunks.py \
  -q
```

Frontend build:

```bash
cd frontend
npm run build
```

## Embedding Smoke Test

Docker:

```bash
docker compose exec backend python - <<'PY'
from app.rag.embeddings.dense_embedding import dense_embedding
v = dense_embedding.embed_query("测试")
print(len(v), v[:3])
PY
```

Local:

```bash
cd backend
python - <<'PY'
from app.rag.embeddings.dense_embedding import dense_embedding
v = dense_embedding.embed_query("测试")
print(len(v), v[:3])
PY
```

## Baseline Evaluation

Run the enterprise baseline test set after retrieval, prompt, tag, or chunking changes.

Retrieval-only mode is fastest:

```bash
cd backend
python scripts/eval_golden_set.py \
  --golden-set ../data/challenge_golden_set_v1.jsonl \
  --api-base http://127.0.0.1:8010/api \
  --mode retrieval_only \
  --concurrency 4 \
  --output ../data/challenge_golden_set_v1_results.jsonl
```

Full answer mode with judge:

```bash
cd backend
python scripts/eval_golden_set.py \
  --golden-set ../data/challenge_golden_set_v1.jsonl \
  --api-base http://127.0.0.1:8010/api \
  --mode full \
  --judge \
  --output ../data/challenge_golden_set_v1_results.jsonl
```

Run a slice:

```bash
cd backend
python scripts/eval_golden_set.py \
  --golden-set ../data/challenge_golden_set_v1.jsonl \
  --api-base http://127.0.0.1:8010/api \
  --mode retrieval_only \
  --slice recall
```

Useful slices:

```text
balanced
exact
recall
discovery
strict
```

The same cases can also be managed from the Quality Center. The UI exposes three run modes: `仅检索`, `轻答案`, and `完整`; the smoke set is a stable subset filter for quick checks.

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

## Demo Data

Default:

```text
data/enterprise_docs
```

The legacy PDF stock-report demo is still available:

```bash
docker compose exec backend python scripts/seed_demo.py --data-dir "../data/stock reports"
```

That path requires a valid MinerU token for PDF parsing.

## Troubleshooting

Milvus collection missing:

```bash
docker compose exec backend python scripts/reset_milvus_collection.py
docker compose exec backend python scripts/seed_demo.py
```

Backend logs:

```bash
docker compose logs --tail=160 backend
```

Milvus logs:

```bash
docker compose logs --tail=160 milvus-standalone
```

Stop services:

```bash
docker compose down
```
