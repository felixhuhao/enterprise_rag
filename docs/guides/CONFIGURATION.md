# Configuration

The application uses `pydantic-settings` and reads environment variables from `.env` files.

Root `.env` is intended for Docker Compose. `backend/.env` can be used for local backend runs.

The root `.env.example` is optimized for Docker deployment on small servers and
therefore defaults to Qwen remote embeddings and Qwen-VL image descriptions.
The Python `Settings` class keeps the backward-compatible local embedding
default for bare backend runs without an env file, but image description also
defaults to Qwen-VL.

## Required For A Useful Demo

| Variable | Description |
|---|---|
| `API_TOKEN` | Env-managed **bootstrap admin** credential for lockout recovery. Not the normal client auth path — users sign in via the login screen with username/password. Keep a private value outside local demos. |
| `EMBEDDING_PROVIDER` | `local` (BGE-M3/FlagEmbedding) or `qwen` (remote Qwen `text-embedding-v4`). `qwen` is recommended for small servers; `local` is the backward-compatible default. |
| `EMBEDDING_MODEL_HOST_PATH` | Required only when `EMBEDDING_PROVIDER=local`. Host path to the local embedding model mounted into Docker, e.g. `/home/hao/models/BAAI/bge-m3`. |
| `EMBEDDING_MODEL_PATH` | Runtime model path (local provider only). Docker uses `/models/embedding`; local dev can use `/home/hao/models/BAAI/bge-m3`. |
| `DEEPSEEK_API_KEY` | DeepSeek-compatible API key for chat, HyDE, query expansion, rerank, and judge evaluation. |
| `QWEN_API_KEY` | Required when `EMBEDDING_PROVIDER=qwen` and/or `IMAGE_DESCRIPTION_PROVIDER=qwen`. Qwen/DashScope OpenAI-compatible API key. |
| `ZHIPU_API_KEY` | Required only when `IMAGE_DESCRIPTION_PROVIDER=zhipu`. Zhipu-compatible API key for image descriptions. |

PDF parsing additionally requires:

| Variable | Description |
|---|---|
| `MINERU_API_TOKEN` | MinerU token. Markdown and Markdown ZIP ingestion do not require this. |

## Full Environment Reference

### API / App

| Variable | Default | Description |
|---|---|---|
| `API_TOKEN` | `enterprise-rag-dev-token` in examples | Env-managed bootstrap admin credential. Accepted directly by `lookup_user` (bypassing the `sessions` table) and resolved to the pinned bootstrap admin row, so an operator is never locked out. Not a session: logout does not invalidate it, and it should not be rotated through the app UI. Normal access is via login. |
| `RATE_LIMIT_PER_MINUTE` | `60` | Per-token API rate limit. |
| `CORS_ORIGINS` | `["http://localhost:5173","http://localhost:4173"]` | Allowed frontend origins. |

### Frontend Feature Flags

| Variable | Default | Description |
|---|---|---|
| `VITE_ENABLE_TAG_GOVERNANCE` | `false` | Show the experimental structured tag governance settings tab. Hidden by default while rule-based chunk enrichment is disabled pending redesign. |

### Local Storage

| Variable | Default | Description |
|---|---|---|
| `GENERAL_UPLOAD_DIR` | `./data/general_uploads` | Uploaded source artifact directory. |
| `GENERAL_PARSED_DIR` | `./data/general_parsed` | Parsed markdown, chunks, images, and quality artifacts. |
| `DATABASE_PATH` | `./data/app.db` | SQLite database path. |
| `STORAGE_MIN_FREE_MB` | `1024` | Warning threshold for free disk space. |

### LLM Service

| Variable | Default | Description |
|---|---|---|
| `DEEPSEEK_API_KEY` | empty | API key for the DeepSeek-compatible chat endpoint. |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI-compatible chat endpoint base URL. |
| `CHAT_MODEL` | `deepseek-v4-flash` | Chat model name. |
| `CHAT_TIMEOUT` | `180` | Chat completion timeout in seconds. |
| `CHAT_TEMPERATURE` | `0.0` | Temperature for final answer generation. |
| `CHAT_MAX_TOKENS` | `1600` | Maximum tokens for final answer generation. |
| `HYDE_TEMPERATURE` | `0.3` | Temperature for HyDE hypothetical text generation. |
| `HYDE_MAX_TOKENS` | `256` | Maximum tokens for HyDE hypothetical text generation. |
| `QUERY_EXPANSION_TEMPERATURE` | `0.3` | Temperature for query expansion generation. |
| `QUERY_EXPANSION_MAX_TOKENS` | `256` | Maximum tokens for query expansion output. |
| `RERANK_MAX_TOKENS` | `128` | Maximum tokens for rerank score JSON output. |
| `GROUNDEDNESS_TEMPERATURE` | `0.0` | Temperature for groundedness judge calls. |
| `GROUNDEDNESS_MAX_TOKENS` | `1800` | Maximum tokens for groundedness judge JSON output. |
| `LOCAL_MODEL_URL` | empty | Optional local/vLLM-compatible model endpoint. |
| `LOCAL_MODEL_NAME` | empty | Optional local model name. |

### Embedding

| Variable | Default | Description |
|---|---|---|
| `EMBEDDING_PROVIDER` | `local` in code, `qwen` in root Docker example | `local` (BGE-M3/FlagEmbedding) or `qwen` (remote Qwen `text-embedding-v4` via OpenAI-compatible API). `qwen` avoids `torch`/`FlagEmbedding` and the BGE-M3 model download. |
| `EMBEDDING_MODEL_HOST_PATH` | `/home/hao/models/BAAI/bge-m3` in examples | Host path mounted into Docker (local provider only). |
| `EMBEDDING_MODEL_NAME` | `bge-m3` | Model name (`text-embedding-v4` for Qwen). Shown in diagnostics as `<provider>/<model>`. |
| `EMBEDDING_MODEL_PATH` | `/models/embedding` | Runtime model path inside backend process (local provider only). |
| `EMBEDDING_DIM` | `1024` | Expected dense vector dimension. |
| `EMBEDDING_BATCH_SIZE` | `4` | Batch size for document embeddings. Capped at 10 for the Qwen provider. |
| `EMBEDDING_MAX_LENGTH` | `8192` | Max token length passed to the local model; used as a name only for the Qwen provider (API rejects oversized input). |
| `EMBEDDING_DEVICE` | `auto` | `auto`, `cuda`, or `cpu`. Local provider only; reported as `remote` for Qwen. |
| `EMBEDDING_USE_FP16` | `true` | Uses fp16 only when CUDA is active (local provider only). |
| `EMBEDDING_TIMEOUT` | `30` | Remote embedding request timeout in seconds (Qwen only). |
| `EMBEDDING_MAX_RETRIES` | `2` | OpenAI SDK retry count for transient (408/409/429/5xx) failures (Qwen only). |
| `QWEN_API_KEY` | empty | Qwen/DashScope API key. Required when `EMBEDDING_PROVIDER=qwen`. |
| `QWEN_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | Qwen OpenAI-compatible base URL. |

> **Vector-space safety:** changing `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL_NAME`, or `EMBEDDING_DIM` changes the vector space even when the dimension stays 1024. The collection records an embedding fingerprint and query/upsert are blocked on mismatch or a missing fingerprint. After switching: reset and reindex (`scripts/reset_milvus_collection.py`); to adopt an unchanged-provider collection, pin the fingerprint (`scripts/pin_embedding_fingerprint.py --yes`).

### MinerU PDF Parsing

| Variable | Default | Description |
|---|---|---|
| `MINERU_BASE_URL` | `https://mineru.net/api/v4` | MinerU API base URL. |
| `MINERU_API_TOKEN` | empty | Required for PDF parsing. |
| `MINERU_MODEL_VERSION` | `vlm` | MinerU parser model version. |
| `MINERU_POLL_INTERVAL` | `3` | Poll interval in seconds. |
| `MINERU_POLL_TIMEOUT` | `1800` | Poll timeout in seconds. |
| `MINERU_UPLOAD_TIMEOUT` | `300` | Upload timeout in seconds. |
| `MINERU_DOWNLOAD_TIMEOUT` | `300` | Download timeout in seconds. |

### Milvus

| Variable | Default | Description |
|---|---|---|
| `MILVUS_URI` | `http://localhost:19530` | Milvus connection URI. Docker Compose overrides it to `http://milvus-standalone:19530`. |
| `MILVUS_REQUIRED_ON_STARTUP` | `false` | If true, backend startup fails when Milvus is unreachable. |
| `MILVUS_HEALTH_TIMEOUT_SECONDS` | `2.0` | Timeout for Milvus startup and health probes. |

### Upload Limits

| Variable | Default | Description |
|---|---|---|
| `MD_ZIP_MAX_SIZE_MB` | `50` | Maximum Markdown ZIP upload size. |
| `UPLOAD_MAX_SIZE_MB` | `100` | Maximum single upload size. |

### Chunk Search Enrichment

| Variable | Default | Description |
|---|---|---|
| `CHUNK_ENRICHMENT_ENABLED` | `false` | Enable rule-based chunk search metadata enrichment during ingestion. Disabled by default until redesigned. |
| `CHUNK_ENRICHMENT_PROFILE` | `none` | Enrichment profile to use when enabled. Use `enterprise_policy` to restore the legacy policy-rule enrichment. |

> Breaking change: deployments that previously relied on rule-based `keywords`, `structured_tags`, or enriched sparse/BM25 `search_text` should explicitly set `CHUNK_ENRICHMENT_ENABLED=true` and `CHUNK_ENRICHMENT_PROFILE=enterprise_policy` until their documents are reprocessed and retrieval quality is re-evaluated.

### Image Description

| Variable | Default | Description |
|---|---|---|
| `IMAGE_DESCRIPTION_PROVIDER` | `qwen` | `qwen` (Qwen-VL) or `zhipu` (GLM-4.6V). Selects the API key/base URL pair. |
| `ZHIPU_API_KEY` | empty | API key for image descriptions (provider=zhipu). |
| `ZHIPU_BASE_URL` | `https://open.bigmodel.cn/api/paas/v4` | Zhipu-compatible API base URL. |
| `IMAGE_DESCRIPTION_ENABLED` | `true` | Enable image-to-text description during ingestion. |
| `IMAGE_DESCRIPTION_MODEL` | `qwen3-vl-flash` | Image description model name. Use `glm-4.6v-flash` for Zhipu. |
| `IMAGE_DESCRIPTION_CONCURRENCY` | `3` | Concurrent image description requests. |
| `IMAGE_DESCRIPTION_TIMEOUT` | `30` | Per-request timeout in seconds. |
| `IMAGE_DESCRIPTION_MAX_TOKENS` | `800` | Maximum tokens for each image description response. |
| `IMAGE_DESCRIPTION_MAX_SIZE_MB` | `10` | Skip image description for images larger than this size. |

## Example Docker `.env`

```env
API_TOKEN=enterprise-rag-dev-token
EMBEDDING_MODEL_HOST_PATH=/home/hao/models/BAAI/bge-m3
EMBEDDING_MODEL_NAME=bge-m3
EMBEDDING_MODEL_PATH=/models/embedding
DEEPSEEK_API_KEY=sk-your-deepseek-api-key
ZHIPU_API_KEY=your-zhipu-api-key
MINERU_API_TOKEN=
MILVUS_URI=http://localhost:19530
VITE_ENABLE_TAG_GOVERNANCE=false
```

## Example Local Backend `.env`

```env
API_TOKEN=enterprise-rag-dev-token
EMBEDDING_MODEL_PATH=/home/hao/models/BAAI/bge-m3
DEEPSEEK_API_KEY=sk-your-deepseek-api-key
ZHIPU_API_KEY=your-zhipu-api-key
MILVUS_URI=http://localhost:19530
```

## Example Qwen (Small-Server) `.env`

No local model download, no `torch`/`FlagEmbedding` in the process:

```env
EMBEDDING_PROVIDER=qwen
EMBEDDING_MODEL_NAME=text-embedding-v4
EMBEDDING_DIM=1024
EMBEDDING_BATCH_SIZE=10
EMBEDDING_TIMEOUT=30
EMBEDDING_MAX_RETRIES=2
QWEN_API_KEY=your-qwen-api-key
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

IMAGE_DESCRIPTION_PROVIDER=qwen
IMAGE_DESCRIPTION_MODEL=qwen3-vl-flash
IMAGE_DESCRIPTION_ENABLED=true
```

After switching providers, reset and reindex:

```bash
docker compose exec backend python scripts/reset_milvus_collection.py
docker compose exec backend python scripts/seed_demo.py
```

To adopt an existing collection on an unchanged provider (non-destructive):

```bash
docker compose exec backend python scripts/pin_embedding_fingerprint.py --yes
```
