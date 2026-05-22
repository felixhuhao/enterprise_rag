# Enterprise RAG Platform

Enterprise RAG Platform is a document intelligence system built with FastAPI, Vue 3, LangGraph, Milvus, and text-first multimodal processing.

It supports PDF, Markdown, and Markdown ZIP ingestion, converts tables and images into text evidence, stores chunks in Milvus, and provides streaming question answering with citations, retrieval trace, runtime settings, query statistics, and golden set evaluation.

## Highlights

- **General document ingestion**: upload `.pdf`, `.md`, `.markdown`, and `.zip` packages.
- **MinerU online parsing**: convert PDFs into Markdown, tables, and image assets.
- **Markdown ZIP support**: ingest `document.md + images/` archives without PDF parsing.
- **Text-first image support**: describe extracted images with a VL model, then index descriptions with `text-embedding-v4`.
- **Table-aware chunking**: split small tables as full chunks and large tables as row groups with raw-table traceability.
- **Hybrid retrieval**: Milvus dense vector search plus BM25 sparse retrieval, RRF fusion, optional HyDE, rerank, and entity filter fallback.
- **Evidence-first answers**: streaming answers with numbered citations, image evidence thumbnails, and citation validation.
- **Observability**: per-message retrieval trace, rerank debug output, query run stats, and structured error codes.
- **Evaluation**: golden set runner with rule scoring, citation scoring, no-answer checks, and optional LLM judge.

## Architecture

```text
PDF / MD / ZIP Upload
  -> FastAPI Documents API
  -> LangGraph ingestion workflow
  -> MinerU / Markdown / Markdown ZIP parser
  -> image-to-text enrichment
  -> Markdown + table chunking
  -> text-embedding-v4
  -> Milvus general_documents

User Query
  -> FastAPI SSE Query API
  -> entity confirm / rewrite / search / HyDE / RRF / table expand / rerank
  -> prompt builder
  -> streaming LLM answer
  -> citations + trace + query stats
  -> Vue frontend
```

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, Uvicorn, Pydantic Settings |
| Workflow | LangGraph |
| Vector store | Milvus dense vector + BM25 sparse field |
| Embedding | DashScope `text-embedding-v4` |
| PDF parsing | MinerU Online API |
| Image-to-text | Qwen-VL compatible vision model |
| App state | SQLite |
| Frontend | Vue 3, TypeScript, Pinia, Arco Design Vue |
| Evaluation | JSONL golden sets + local evaluation runner |

## Main Features

### Document Ingestion

Supported input formats:

- `.pdf`
- `.md`
- `.markdown`
- `.zip` with the recommended structure:

```text
upload.zip
  document.md
  images/
```

The ingestion workflow stores upload state in SQLite and writes searchable chunks into Milvus. It is idempotent by `document_id`, so retrying a document does not duplicate chunks.

### Image-To-Text

The platform keeps retrieval text-first. Images extracted from PDFs or Markdown ZIP packages are described during ingestion, injected into nearby text chunks, embedded with the same text embedding model, and exposed through citation metadata.

This avoids a separate VL embedding space while still making charts, screenshots, and figures searchable and auditable.

### Query Pipeline

The query path supports:

- entity confirmation and safe fallback
- query rewrite
- hybrid dense + sparse search
- HyDE search
- RRF fusion
- table expansion
- LLM rerank
- prompt construction
- citation validation
- SSE streaming answer

Runtime settings can switch between faster and more accurate retrieval modes.

### Observability

Each assistant response can expose:

- search mode
- rewritten query
- entity filter result
- rerank debug scores
- selected citations
- retrieval latency breakdown
- generation latency

The Evaluate page focuses on query run statistics rather than subjective answer grading.

### Golden Set Evaluation

The backend includes a standalone runner:

```powershell
cd backend
python scripts/eval_golden_set.py `
  --golden-set ../data/stock_reports_v2.jsonl `
  --api-base http://127.0.0.1:8010/api `
  --judge `
  --output ../data/stock_reports_v2_results.jsonl
```

The runner records actual answers, citations, trace data, rerank debug data, and summary scores. It supports:

- rule-based numeric and keyword scoring
- citation/source recall
- no-answer refusal checks
- optional LLM judge for complex reasoning questions

### Evaluation Runner

`backend/scripts/eval_golden_set.py` is intentionally independent from the application runtime. It calls the running query API, consumes the SSE stream, and writes evaluation artifacts without changing backend or frontend behavior.

Typical command:

```powershell
cd backend
python scripts/eval_golden_set.py `
  --golden-set ../data/stock_reports_v2.jsonl `
  --api-base http://127.0.0.1:8010/api `
  --judge `
  --output ../data/stock_reports_v2_results.jsonl
```

Inputs:

| Field | Purpose |
|---|---|
| `id` | Stable case id. |
| `question` | User-facing query sent to the API. |
| `eval_type` | `rule`, `llm_judge`, or `no_answer`. |
| `numeric_expectations` | Numeric checks with tolerance for rule cases. |
| `must_have` / `nice_to_have` | Required and optional answer keywords. |
| `expected_documents` | Expected citation source substrings. |
| `min_expected_citations` | Minimum number of source matches required. |
| `expected_points` | LLM judge checklist for complex cases. |
| `no_answer_type` | Refusal scenario, such as missing actual value or out-of-scope entity. |

Scoring:

| Type | What It Measures |
|---|---|
| `rule` | Numeric tolerance, required keywords, optional keywords, and citation recall. |
| `llm_judge` | Complex reasoning quality against expected points, plus citation recall. |
| `no_answer` | Whether the assistant refuses correctly instead of inventing unsupported facts. |

Outputs:

```text
*_results.jsonl   # one line per question, with answer, citations, scores, trace, rerank debug
*_summary.json    # overall score, pass rate, per-type breakdown, low-score cases
```

Result interpretation:

- `pass`: case meets the configured threshold.
- `warn`: answer is usable but should be reviewed before release.
- `fail`: answer, citation, or refusal behavior regressed.

The runner is mainly a regression tool. It should be run after changes to chunking, image-to-text, retrieval settings, rerank, prompt construction, or citation handling.

## Demo Dataset

The current local demo uses 6 stock research report PDFs from:

```text
D:\CodeProjects\multimodel_rag_pro\data\stock reports
```

In the repository workspace this is the relative path:

```text
data/
  stock reports/              # 6 PDF reports used as the demo knowledge base
  stock_reports_v2.jsonl      # 17-question golden set
  stock_reports_v2_results.jsonl
  stock_reports_v2_summary.json
```

The raw demo documents and evaluation outputs are local runtime data and are not committed by default.

### Demo Setup

1. Start Milvus and the backend service.
2. Upload all PDFs in `data/stock reports/` from the Documents page.
3. Set the document subject when needed, then process each document.
4. Confirm every document reaches `completed`.
5. Run the golden set:

```powershell
cd backend
python scripts/eval_golden_set.py `
  --golden-set ../data/stock_reports_v2.jsonl `
  --api-base http://127.0.0.1:8010/api `
  --judge `
  --output ../data/stock_reports_v2_results.jsonl
```

### Current Baseline

Latest local run:

```text
Questions: 17
Types: rule=10, llm_judge=5, no_answer=2

Overall:   avg=0.960, pass_rate=100.0%
Rule:      avg=0.968, pass_rate=100.0%
LLM judge: avg=0.928, pass_rate=100.0%
No-answer: avg=1.000, pass_rate=100.0%
```

This baseline is used as a regression check. After changes to ingestion, retrieval, rerank, image-to-text, or prompt construction, rerun the same golden set and compare:

- overall score should stay close to the baseline
- no-answer cases should remain pass
- citation recall should not degrade noticeably
- low-score cases should be investigated before release

## Project Structure

```text
multimodel_rag_pro/
  backend/
    app/
      api/                  # documents, query chat, query stats, settings
      core/                 # database and runtime settings
      rag/
        chunking/           # Markdown and table chunking
        embeddings/         # text-embedding-v4 client
        ingestion/          # LangGraph ingestion workflow
        parsing/            # MinerU, Markdown, image describer, ZIP parser
        query/              # search, fusion, rerank, prompt, citation validation
        vectorstores/       # Milvus collection management
      services/             # document service, chat history, query stats
    scripts/
      eval_golden_set.py
    tests/
  frontend/
    src/
      api/
      components/
        documents/
        evaluate/
        layout/
        query-chat/
        settings/
      stores/
      utils/
```

## Configuration

Create `backend/.env`:

```env
API_TOKEN=rag-pro-secret-token
DASHSCOPE_API_KEY=your_dashscope_key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
CHAT_MODEL=qwen-plus

MINERU_API_TOKEN=your_mineru_token
MINERU_BASE_URL=https://mineru.net/api/v4

MILVUS_URI=http://localhost:19530
```

Optional image settings:

```env
IMAGE_DESCRIPTION_ENABLED=true
IMAGE_DESCRIPTION_MODEL=qwen3-vl-flash
IMAGE_DESCRIPTION_CONCURRENCY=3
IMAGE_DESCRIPTION_TIMEOUT=30
IMAGE_DESCRIPTION_MAX_SIZE_MB=10
MD_ZIP_MAX_SIZE_MB=50
```

## Running Locally

Start backend:

```powershell
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
```

Start frontend:

```powershell
cd frontend
npm install
npm run dev
```

Open the Vite URL shown in the terminal, usually:

```text
http://127.0.0.1:5173
```

## Verification

Backend:

```powershell
cd backend
python -m compileall app
python -m pytest tests/unit -v --basetemp .pytest_tmp_verify -p no:cacheprovider
```

Frontend:

```powershell
cd frontend
npm run build
```

Golden set:

```powershell
cd backend
python scripts/eval_golden_set.py `
  --golden-set ../data/stock_reports_v2.jsonl `
  --api-base http://127.0.0.1:8010/api `
  --judge `
  --output ../data/stock_reports_v2_results.jsonl
```

## Current Scope

This project is intentionally a general enterprise RAG platform. Financial documents are used as one demonstration dataset, but financial-specific enrichment, metric extraction, and structured stock analytics are treated as future domain extensions.

Current non-goals:

- native VL embedding retrieval
- separate image vector space
- query-time image understanding
- financial-only schema fields in the general Milvus collection
- external monitoring stack

## Roadmap

- Expand integration tests for real Milvus and MinerU environments.
- Add more reusable demo datasets and golden sets.
- Improve report export for evaluation summaries.
- Add optional domain packs, such as financial report analysis.
- Explore structured data analytics as a separate add-on.
