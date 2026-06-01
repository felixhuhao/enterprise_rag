# CONTEXT_HANDOFF

## Project Identity

Product name: Enterprise RAG Platform.
Current folder detected by this session: D:\CodeProjects\enterprise_rag.
Folder spelling is now the intended enterprise_rag.
Previous project/folder names have been cleaned from text files; app.db may still contain old strings as SQLite runtime state.

This project is now positioned as a general enterprise document RAG platform, not a financial-only app and not a native multimodal embedding app.
The key product direction is text-first multimodal: images and charts are converted into text descriptions during ingestion, then retrieved through the normal text pipeline.

## Latest Commit

Latest completed commit before the documentation wrap-up: e56b707 Complete Phase 10 tag tuning and golden fixes.
Working tree was clean after that commit.

That commit included Phase 10 tag governance/tuning, baseline case fixes, and the final retrieval fixes needed for the enabled baseline cases to pass.

## Current Architecture

Backend: FastAPI, LangGraph, SQLite app state, Milvus general_documents, local dense embedding model, MinerU Online, DeepSeek-compatible chat model, and image-to-text ingestion.
Frontend: Vue 3, TypeScript, Pinia, Arco Design Vue.
Main pages: Query Chat, Documents, Entity Aliases, Permission Audit, Quality Center, Retrieval Test, Settings.

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

Pipeline order: entity_confirm, plan_query, rewrite_query, direct search / HyDE / query expansion / multi-hop depending on retrieval flavor, rrf_fusion, table_expand, rerank, diversify_context, context_expand, build_prompt, generate, groundedness, validate_citations.
Retrieval flavors are balanced, exact, recall, and discovery. Strict evidence is independent from retrieval flavor and controls answer behavior, not recall strategy.
Entity filter exists but must be defensive with fallback when filtered results are too few or too weak.
Observability implemented: SSE trace events, query expansion trace, rerank debug, citations, groundedness, query stats persistence, per-flavor stats, retrieval-test traces, and Quality Center records.
Prompts were generalized from financial-only wording to enterprise document wording in build_prompt.py and hyde_search.py.

## Baseline Test Set And Demo Data

Main demo corpus is the Markdown enterprise document set under data/enterprise_docs.
Main baseline test set is data/challenge_golden_set_v1.jsonl.
Enabled baseline cases were manually validated through the UI and pass after the latest retrieval/tag fixes.

Eval command: cd backend; python scripts/eval_golden_set.py --golden-set ../data/challenge_golden_set_v1.jsonl --api-base http://127.0.0.1:8010/api --judge --output ../data/challenge_golden_set_v1_results.jsonl.

Evaluation design: rule scoring uses numeric tolerance, must_have, nice_to_have, and citation score. LLM judge is used only for complex reasoning questions. No-answer tests correct refusal. Citation/source is a common scoring axis. Feedback can be promoted to draft baseline cases, edited, published, enabled/disabled, and run from the Quality Center.

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
