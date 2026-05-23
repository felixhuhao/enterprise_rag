# CONTEXT_HANDOFF

## Project Identity

Product name: Enterprise RAG Platform.
Current folder detected by this session: D:\CodeProjects\enterprise_rag.
Folder spelling is now the intended enterprise_rag.
Previous project/folder names have been cleaned from text files; app.db may still contain old strings as SQLite runtime state.

This project is now positioned as a general enterprise document RAG platform, not a financial-only app and not a native multimodal embedding app.
The key product direction is text-first multimodal: images and charts are converted into text descriptions during ingestion, then retrieved through the normal text pipeline.

## Latest Commit

Last completed commit before the rename: 4b76f80 docs:enterprise-rag-platform-positioning.
Working tree was clean after that commit.

That commit included README rewrite, FastAPI metadata update, frontend title update, and query/HyDE prompt generalization from financial docs to enterprise docs.

## Current Architecture

Backend: FastAPI, LangGraph, SQLite app state, Milvus general_documents, DashScope text-embedding-v4, MinerU Online, Qwen-VL compatible image description.
Frontend: Vue 3, TypeScript, Pinia, Arco Design Vue.
Main pages: Query Chat, Documents, Evaluate / Query Stats, Settings.

Important backend areas:
- backend/app/api/documents.py
- backend/app/api/query_chat.py
- backend/app/api/query_stats.py
- backend/app/core/database.py
- backend/app/core/runtime_settings.py
- backend/app/rag/ingestion/graph.py
- backend/app/rag/parsing/mineru_parser.py
- backend/app/rag/parsing/image_describer.py
- backend/app/rag/chunking/markdown_chunker.py
- backend/app/rag/vectorstores/general_milvus.py
- backend/app/rag/query/search.py
- backend/app/rag/query/hyde_search.py
- backend/app/rag/query/build_prompt.py
- backend/scripts/eval_golden_set.py

Important frontend areas:
- frontend/src/components/layout/AppLayout.vue
- frontend/src/components/documents/DocumentsView.vue
- frontend/src/components/query-chat/
- frontend/src/components/evaluate/
- frontend/src/components/settings/SettingsView.vue

## Implemented Ingestion Capabilities

Supported uploads: .pdf, .md, .markdown, .zip.
Markdown ZIP recommended structure: upload.zip with document.md and optional images/.
Markdown ZIP boundary: only recommended document.md + images/ is guaranteed. Nested md is tolerated but image path repair is not guaranteed. No complex path rewriting in P1.

PDF uses MinerU Online. PDF and Markdown ZIP images go through image-to-text. Descriptions are injected before text splitting, then embedded as normal text.
No native VL embedding and no separate image vector space. Query-time VL calls are intentionally avoided.

Tables: small tables produce table_summary + table_full. Large tables produce table_summary + table_row_group + raw_table_path. Page-level parent retrieval was removed; section/table context expansion is preferred.

P1 image work completed: image_paths citation passthrough, safe asset endpoint, frontend citation thumbnail / preview, and Markdown ZIP support.

## Query Pipeline And Observability

Pipeline order: entity_confirm, rewrite_query, search and hyde_search in parallel, rrf_fusion, table_expand, rerank, build_prompt, generate, validate_citations.
Runtime settings use presets instead of exposing every low-level toggle. User wanted fewer random combinations and simpler UI.
Entity filter exists but must be defensive with fallback when filtered results are too few or too weak.
Observability implemented: SSE trace events, rerank debug, citations, query stats persistence, and Evaluate page focused on query run statistics.
Old answer evaluation page and legacy knowledge, graph, OCR, and evaluate code were cleaned up earlier.
Prompts were generalized from financial-only wording to enterprise document wording in build_prompt.py and hyde_search.py.

## Golden Set And Demo Data

Main demo corpus is 6 stock research report PDFs under data/stock reports.
Main golden set is data/stock_reports_v2.jsonl with 17 questions: rule=10, llm_judge=5, no_answer=2.

Latest baseline: overall avg 0.960, pass_rate 100 percent. Rule avg 0.968. LLM judge avg 0.928. No-answer avg 1.000.

Eval command: cd backend; python scripts/eval_golden_set.py --golden-set ../data/stock_reports_v2.jsonl --api-base http://127.0.0.1:8010/api --judge --output ../data/stock_reports_v2_results.jsonl.

Image golden set was tested separately with 5 image/chart questions. Average around 0.898, 4 of 5 pass, numeric extraction accurate. One warning was citation mismatch despite correct answer.

Evaluation design: rule scoring uses numeric tolerance, must_have, nice_to_have, and citation score. LLM judge is used only for a small number of complex reasoning questions. No-answer tests correct refusal. Citation/source is a common scoring axis.

## Gitignore And Local Data

Ignored by design: .env files, data/, backend/data/, docs/, pycache, pytest temp dirs, frontend dist and node_modules.
User intentionally keeps local planning docs under ignored docs/.
Raw demo PDFs and eval outputs are local runtime data and are not committed by default.

## Verification Commands

Backend compile: cd backend; python -m compileall app.
Backend unit tests: cd backend; python -m pytest tests/unit -v --basetemp .pytest_tmp_verify -p no:cacheprovider.
Frontend build: cd frontend; npm run build.
Vite large chunk warning is currently accepted and not treated as failure.

## Rename Notes

The user renamed the folder after committing. Current detected folder is D:\CodeProjects\enterprise_rag.
The intended folder name is now in place.
Previously stopped PIDs before rename: 52348 npm run dev, 38856 vite cmd, 7064 vite node.

Next new conversation should first run git status --short, then run a stale project-name scan if further path cleanup is needed.
After path cleanup, run compile, tests, and frontend build. Commit rename/path cleanup separately.

## Future Work Discussed

Near term: verify the renamed folder, clean stale paths, run tests/build, then commit path cleanup.
Potential next work: integration tests with real Milvus and MinerU, better eval report export, more reusable demo datasets, optional financial domain pack.

ChatBI note: D:\CodeProjects\chatbi_nanobot was reviewed. It is useful as future structured analytics add-on, but do not directly merge Nanobot or Gradio architecture. Borrow Text-to-SQL, SQL safety, ARIMA/Bollinger tools, and chart ideas later in current FastAPI/Vue style.

## User Preferences

Keep the project general, not too financial-vertical.
Prefer text-first image-to-text over native multimodal embeddings.
Prefer clean industrial architecture over one-off demos.
Golden set should be automated and quantitative.
Demo and golden data can remain local and ignored unless explicitly promoted.
Avoid large new architecture changes without planning first.
