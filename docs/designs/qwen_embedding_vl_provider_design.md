# Design — Qwen Embedding And VL Providers

**Date:** 2026-06-20
**Status:** Proposed

## Goal

Support small-server deployment by moving the production embedding path from local
BGE-M3 to Qwen `text-embedding-v4`, while keeping local BGE-M3 as an optional
compatibility mode. Also allow image description to use Qwen-VL with the same
OpenAI-compatible request style already used by the current GLM-4.6V integration.

The main target environment is a 4c / 4 GB RAM / slow-download server where
installing `torch`, `FlagEmbedding`, and BGE-M3 model files is expensive in disk,
download time, and runtime memory.

## Non-Goals

- Do not introduce multimodal embeddings or a visual vector collection.
- Do not change Milvus schema beyond the existing `EMBEDDING_DIM` setting.
- Do not change chunking, retrieval planning, rerank, citation, or prompt logic.
- Do not remove BGE-M3 support for local/offline development.

## Current State

Embedding:

- `backend/app/rag/embeddings/dense_embedding.py` imports `torch` and
  `FlagEmbedding` inside `_get_model`.
- The public interface is already small:
  - `dense_embedding.embed_documents(...)`
  - `dense_embedding.embed_query(...)`
  - `embed_chunks(...)`
- Milvus uses `settings.EMBEDDING_DIM` for the `dense` vector field.

Image description:

- `backend/app/rag/parsing/image_describer.py` uses `AsyncOpenAI`.
- The request is already OpenAI-compatible chat completions with `image_url` and
  text content.
- This shape is compatible with Qwen-VL / DashScope-compatible endpoints.

## Design

### 1. Embedding Provider Switch

Add:

```env
EMBEDDING_PROVIDER=local
```

Allowed values:

| Value | Meaning |
|---|---|
| `local` | Existing BGE-M3 / FlagEmbedding path. Default for backward compatibility. |
| `qwen` | Remote OpenAI-compatible Qwen embedding API. Recommended for small servers. |

Add Qwen-compatible API settings:

```env
QWEN_API_KEY=
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

Keep existing embedding settings:

```env
EMBEDDING_MODEL_NAME=bge-m3
EMBEDDING_DIM=1024
EMBEDDING_BATCH_SIZE=4
EMBEDDING_MAX_LENGTH=8192
```

For Qwen deployment:

```env
EMBEDDING_PROVIDER=qwen
EMBEDDING_MODEL_NAME=text-embedding-v4
EMBEDDING_DIM=1024
EMBEDDING_BATCH_SIZE=10
QWEN_API_KEY=...
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

### 2. Keep The Embedding Interface Stable

Refactor `dense_embedding.py` internally, but keep imports and callers stable.

Proposed structure:

```text
dense_embedding.py
  LocalBgeDenseEmbedding
  QwenDenseEmbedding
  get_dense_embedding()
  dense_embedding
  embed_chunks()
```

`dense_embedding` remains the object imported by search, HyDE, retrieval test,
and ingestion code. This avoids touching the rest of the RAG pipeline.

### 3. Qwen Embedding Behavior

Use the existing `openai` package:

```python
client = OpenAI(api_key=settings.QWEN_API_KEY, base_url=settings.QWEN_BASE_URL)
client.embeddings.create(
    model=settings.EMBEDDING_MODEL_NAME,
    input=batch,
    dimensions=settings.EMBEDDING_DIM,
    encoding_format="float",
)
```

Rules:

- Raise a clear error when `EMBEDDING_PROVIDER=qwen` and `QWEN_API_KEY` is empty.
- Batch requests using `EMBEDDING_BATCH_SIZE`.
- For Qwen `text-embedding-v4`, cap effective batch size at 10 or fail fast if
  configured above 10. Prefer fail-fast so config mistakes are visible.
- Honor `EMBEDDING_TIMEOUT` for remote calls.
- Preserve result order using response item `index`.
- Keep existing dimension validation in `embed_chunks`.
- Keep `embed_query` as one-item embedding.

Official DashScope docs list `dimensions` as an OpenAI-compatible request
parameter for `text-embedding-v4`, with supported values including 1024. They
also list max batch size 10 and max 8192 tokens per input item. Implementation
must still include a live smoke test because tenant/region/model behavior can
drift from docs.

### 4. Qwen Input Limits

`EMBEDDING_MAX_LENGTH` currently only applies to local `model.encode(...)`. For
Qwen, use it as a validation limit name, not a tokenizer-accurate truncation
mechanism.

Implementation:

- Do not silently truncate. Truncation can damage retrieval and make indexed
  evidence differ from source chunks.
- Add a preflight character-size guard as a cheap safety check, but keep the API
  response as the source of truth for token overflows.
- Raise a clear embedding error when DashScope rejects an item for length.
- Document that Qwen `text-embedding-v4` supports 8192 tokens per item and that
  this is a provider limit.

Do not add tokenizer-specific counting in the first implementation. It would add
more dependency and complexity than this deployment path needs.

### 5. Remote Reliability

Add:

```env
EMBEDDING_TIMEOUT=30
EMBEDDING_MAX_RETRIES=2
```

Remote embedding policy:

- Prefer the OpenAI SDK retry policy over a custom retry loop.
- Construct the Qwen embedding client with
  `timeout=settings.EMBEDDING_TIMEOUT` and
  `max_retries=settings.EMBEDDING_MAX_RETRIES`.
- Rely on the SDK's default transient retry behavior for timeout / 408 / 409 /
  429 / 5xx failures.
- Do not retry validation/config errors: missing API key, unsupported dimension,
  oversized input, 400-class non-rate-limit errors.
- Preserve the existing exception surface by raising `RuntimeError` with
  `"Embedding"` / `"embedding"` in the message so `classify_error(...)` maps it
  to `EMBEDDING_ERROR`.
- This wrap is load-bearing: `classify_error(...)` checks embedding text before
  checking whether an exception came from the `openai` module. Raw
  `openai.RateLimitError`, `openai.APITimeoutError`, and
  `openai.APIConnectionError` would otherwise fall through to `LLM_ERROR`.
- Wrap every OpenAI SDK exception after SDK retries are exhausted. Do not allow
  raw OpenAI exceptions to escape the embedding provider.
- Query-side wrapping in `search.py` may stay as-is if the final exception chain
  preserves the embedding marker.

Only add a custom retry loop if the SDK retry policy proves insufficient in a
live smoke test.

### 6. Optional Heavy Dependencies

Local BGE-M3 should import `torch` and `FlagEmbedding` only when
`EMBEDDING_PROVIDER=local`.

Production images for small servers should be able to omit:

```text
torch
FlagEmbedding
```

Implementation options:

1. Minimal first step:
   - Keep requirements unchanged.
   - Avoid importing heavy libraries unless local provider is active.
   - This reduces runtime memory but not image/download size.

2. Deployment-friendly step:
   - Split requirements into base and local-embedding extras, for example:
     - `requirements.txt`
     - `requirements-local-embedding.txt`
   - Docker production image installs only base requirements by default.

Recommended implementation: do step 1 first, then step 2 if deployment size is
still painful.

### 7. Vector-Space Fingerprint Guard

Documentation alone is not enough. Switching from BGE-M3 to Qwen with the same
1024 dimensions can silently mix incompatible vector spaces.

Add a fingerprint:

```text
embedding_provider
embedding_model_name
embedding_dim
```

Persist it with the Milvus collection using collection properties/metadata if
available in the installed Milvus client. If collection metadata is not reliable
for this SDK/version, persist the fingerprint in the existing SQLite runtime
settings KV store:

```text
milvus.<collection>.embedding_fingerprint
```

Current store: `app/core/runtime_settings.py`, backed by the `settings` table.

Guard behavior:

- `ensure_collection()` records the fingerprint when creating the collection.
- Existing collection with no stored fingerprint uses the **strict default**:
  block query/upsert until an operator explicitly adopts or resets the
  collection. Do not auto-seed missing fingerprints from current settings.
- Ship a non-destructive adoption tool in the same release as the guard:
  `scripts/pin_embedding_fingerprint.py`. This is not optional/later because
  existing unchanged-provider deployments need a safe upgrade path.
- The pin tool writes the current configured fingerprint only after showing the
  target collection, current provider/model/dim, and a warning that it must only
  be used when the existing indexed data was produced by those same settings.
  It should support a non-interactive `--yes` for Docker/CI use.
- Query and upsert paths compare current settings against stored fingerprint.
- On missing or mismatched fingerprint, fail fast with an
  `EMBEDDING_ERROR`-classified message explaining that the collection must be
  pinned with `pin_embedding_fingerprint.py` or reset and reindexed.
- `reset_milvus_collection.py` clears the stored fingerprint together with the
  collection reset.

This guard is required before recommending provider switching in production.

Sync-node caveat:

- `runtime_settings.get(...)` is async.
- `runtime_settings.get_cached(...)` is sync but only reads the in-memory cache.
- `main.py` currently preloads the cache at startup with
  `await runtime_settings.get_all()`.
- The guard may use `get_cached(...)` only if startup preload is guaranteed
  before any embed/query/upsert call. Otherwise add a direct sync SQLite read for
  this fingerprint key to avoid an empty-cache false pass.
- Fingerprint writes also need a sync path. `runtime_settings.set(...)` is async,
  while `ensure_collection()` and `upsert_document_chunks(...)` are sync. Either:
  - add a small sync runtime-settings helper for this fingerprint key, or
  - write/create the fingerprint from an async startup hook before sync
    ingestion/query code can run.

Recommended implementation: add dedicated sync helpers in `general_milvus.py` or
a small adjacent module for this fingerprint key. This keeps the guard local to
Milvus/vector-space safety and avoids threading async calls through sync
LangGraph nodes.

Upgrade flow for existing BGE-M3 users who are not switching providers:

```bash
docker compose exec backend python scripts/pin_embedding_fingerprint.py --yes
```

Upgrade flow for users switching from BGE-M3 to Qwen:

```bash
docker compose exec backend python scripts/reset_milvus_collection.py
docker compose exec backend python scripts/seed_demo.py
```

Placement:

- Upsert path: verify in `upsert_document_chunks(...)` immediately after
  `ensure_collection()`.
- Query path: add an explicit `verify_embedding_fingerprint()` call near the
  start of `search_node(...)`, before `dense_embedding.embed_query(...)`.
- Any dense-only retrieval-test helper that bypasses `search_node(...)` should
  also call the same verifier before searching Milvus.

Before implementation, do a short spike against the installed `pymilvus` version
to confirm whether collection-level properties can be created/read reliably. If
not, use the SQLite runtime settings path directly.

### 8. Concurrency

Keep `_MODEL_ENCODE_LOCK` local-provider only.

- Local BGE-M3 uses the lock around `model.encode(...)`.
- Qwen embedding must not take that lock; network calls should be allowed to
  overlap across request-handling threads.
- The Qwen provider may reuse one OpenAI client instance, but client creation
  should not become a global serialization point.

### 9. Docker Compose Behavior

Current Compose requires:

```yaml
${EMBEDDING_MODEL_HOST_PATH:?Set EMBEDDING_MODEL_HOST_PATH in .env}:/models/embedding:ro
```

That is wrong for `EMBEDDING_PROVIDER=qwen`.

Adjust Compose so Qwen deployments do not need a local model mount. Options:

1. Remove the hard requirement and mount a path only when provided.
2. Provide a separate compose override for local embedding.
3. Keep the mount only in dev/local profile.

Recommended: move the BGE-M3 mount to a local-embedding override or profile.
This keeps Qwen production config clean.

Both files must be handled:

- `docker-compose.yml`
- `docker-compose.dev.yml`

Intended default:

- Base Compose should support Qwen with no local model path.
- Local BGE-M3 users opt into a local-embedding override/profile that mounts
  `EMBEDDING_MODEL_HOST_PATH`.

### 10. Image Description Provider Switch

Add:

```env
IMAGE_DESCRIPTION_PROVIDER=qwen
```

Allowed values:

| Value | Meaning |
|---|---|
| `qwen` | Qwen-VL via OpenAI-compatible chat completions. Default. |
| `zhipu` | GLM-4.6V-compatible provider. |

For Qwen-VL:

```env
IMAGE_DESCRIPTION_PROVIDER=qwen
IMAGE_DESCRIPTION_MODEL=qwen3-vl-flash
QWEN_API_KEY=...
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

Alibaba Cloud Model Studio docs list `qwen3-vl-flash` as a stable Qwen3-VL
model. In US deployment mode, use the region-specific model ID if required, such
as `qwen3-vl-flash-us`. Still run the live smoke test because model availability
can vary by account and deployment mode.

The image request body can stay the same:

```json
[
  {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
  {"type": "text", "text": "..."}
]
```

Provider selection only changes API key and base URL:

| Provider | API key | Base URL |
|---|---|---|
| `zhipu` | `ZHIPU_API_KEY` | `ZHIPU_BASE_URL` |
| `qwen` | `QWEN_API_KEY` | `QWEN_BASE_URL` |

### 11. Runtime Info And Diagnostics

Expose provider labels in diagnostics:

- `/api/system/runtime-info`
  - `embedding_provider`
  - `embedding_model`
  - `embedding_dim`
  - `embedding_device`
  - `image_description_provider`
  - `image_description_model`

For `EMBEDDING_PROVIDER=qwen`, report:

```json
"embedding_device": "remote"
```

Retrieval test strategy summaries can keep showing the embedding model label,
but including provider would make support/debugging clearer:

```text
qwen/text-embedding-v4
local/bge-m3
```

Change `retrieval_test_formatting.embedding_model_label(...)` explicitly. Do not
fall back to `EMBEDDING_MODEL_PATH` for Qwen because `/models/embedding` is stale
and misleading in remote-provider mode.

### 12. Reindex Requirement

Changing any of these requires resetting and rebuilding Milvus:

- `EMBEDDING_PROVIDER`
- `EMBEDDING_MODEL_NAME`
- `EMBEDDING_DIM`

Even if both models output 1024 dimensions, switching from BGE-M3 to Qwen changes
the vector space. Old and new vectors must not be mixed in the same collection.

Operational commands stay the same:

```bash
docker compose exec backend python scripts/reset_milvus_collection.py
docker compose exec backend python scripts/seed_demo.py
```

The fingerprint guard in section 7 enforces this at runtime.

### 13. Interface Stability And Test Stubs

The provider factory must not break existing import patterns:

```python
from app.rag.embeddings.dense_embedding import dense_embedding
```

Keep `dense_embedding` as the module-level object used by current callers and
tests. If a factory is added, it should sit behind that object rather than
requiring callers to import the factory.

Existing tests that stub `app.rag.embeddings.dense_embedding` through
`sys.modules` should keep working. New provider tests can patch the provider
factory or the OpenAI client constructor directly.

## Documentation Updates

Update:

- `.env.example`
- `backend/.env.example`
- `docs/guides/CONFIGURATION.md`
- `docs/guides/DEVELOPMENT.md`
- `README.md`

Docs should make Qwen the recommended small-server deployment path and BGE-M3 the
local/offline compatibility path.

## Tests

Add focused unit tests:

- Qwen embedding provider:
  - uses OpenAI-compatible embeddings endpoint
  - passes `model`, `input`, `dimensions`, `encoding_format`
  - preserves output order
  - rejects missing `QWEN_API_KEY`
  - rejects unsupported Qwen batch size above 10
  - applies `EMBEDDING_TIMEOUT`
  - passes `EMBEDDING_MAX_RETRIES` into the OpenAI client constructor
  - relies on SDK retry behavior rather than adding a custom retry loop
  - classifies provider failures as `EMBEDDING_ERROR`
  - wraps real OpenAI SDK exceptions, such as `openai.RateLimitError`, so they
    do not classify as `LLM_ERROR`
  - does not call or initialize the local BGE model path when Qwen is selected
- Local provider:
  - keeps BGE-M3 provider as default
  - keeps `torch` / `FlagEmbedding` imports local to the local provider
- Image description:
  - provider selection picks Zhipu key/base URL for `zhipu`
  - provider selection picks Qwen key/base URL for `qwen`
  - keeps existing image message shape
- Vector fingerprint:
  - records provider/model/dim on collection creation
  - refuses query/upsert when an existing collection has no stored fingerprint
  - refuses query/upsert on fingerprint mismatch
  - reset script clears stale fingerprint
  - pin script writes the current fingerprint without resetting the collection
  - uses `milvus.<collection>.embedding_fingerprint` in existing runtime
    settings if Milvus collection properties are not viable
- Diagnostics:
  - runtime info shows `embedding_device="remote"` for Qwen
  - retrieval test labels show `qwen/text-embedding-v4`
- Config/docs:
  - `.env.example` includes the new provider variables

Add one optional live smoke test script/check for real credentials:

```bash
EMBEDDING_PROVIDER=qwen EMBEDDING_MODEL_NAME=text-embedding-v4 \
EMBEDDING_DIM=1024 python backend/scripts/smoke_test_embedding.py
```

This smoke test must verify the returned vector length is exactly
`settings.EMBEDDING_DIM`.

Add a separate optional Qwen-VL smoke test with a tiny local PNG/JPEG:

```bash
IMAGE_DESCRIPTION_PROVIDER=qwen IMAGE_DESCRIPTION_MODEL=qwen3-vl-flash \
python backend/scripts/smoke_test_image_description.py path/to/image.png
```

This smoke test should verify provider selection, model ID validity, and a
non-empty Chinese description response.

## Rollout Plan

1. Add config fields with backward-compatible defaults.
2. Refactor embedding provider internals without changing callers.
3. Add Qwen embedding implementation, timeout/retry policy, and tests.
4. Add sync fingerprint helpers and `scripts/pin_embedding_fingerprint.py`.
5. Add vector-space fingerprint guard.
6. Add image description provider selection and tests.
7. Update runtime labels, env examples, and docs, including the non-destructive
   pin flow for unchanged-provider upgrades.
8. Adjust both Compose files so Qwen deployment does not require local model mount.
9. Run the live Qwen embedding and Qwen-VL smoke tests with real credentials.
10. Rebuild the index after switching providers.

## Recommended Production Config For 4c4g3m

```env
EMBEDDING_PROVIDER=qwen
EMBEDDING_MODEL_NAME=text-embedding-v4
EMBEDDING_DIM=1024
EMBEDDING_BATCH_SIZE=10
EMBEDDING_TIMEOUT=30
EMBEDDING_MAX_RETRIES=2
QWEN_API_KEY=...
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

IMAGE_DESCRIPTION_PROVIDER=qwen
IMAGE_DESCRIPTION_MODEL=qwen3-vl-flash
IMAGE_DESCRIPTION_ENABLED=true
```

This avoids downloading BGE-M3 and avoids loading `torch` / `FlagEmbedding` in
the production process.
