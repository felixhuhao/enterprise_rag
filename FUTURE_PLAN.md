# Future Plan

This project is close to a polished Enterprise RAG system. Phase 11-14 and Storage Layer Phase 1 are complete, so the next useful work is wrap-up: documentation alignment, final smoke testing, demo polish, and keeping larger governance/operations ideas in inventory until a real deployment goal appears.

## Positioning

Enterprise RAG should stay focused on document intelligence:

- Ingest enterprise documents.
- Build reliable, inspectable knowledge bases.
- Answer with citations and retrieval traces.
- Support evaluation, observability, and operational recovery.

ChatBI should remain a separate project. Fusion between RAG and BI can be discussed as an architectural extension, but merging both into this codebase would dilute the product story.

## Current Wrap-Up Status

Completed product foundation:

- Phase 11: Golden Set Evaluation Loop And Fast Eval Modes.
- Phase 12: Query Observability And Latency/Cost Profile.
- Phase 13: Document Parsing And Chunk Quality Governance.
- Phase 14: Background Job Reliability P1.
- Storage Layer Maturity Phase 1: SQLite hardening, startup guards, and health payload.
- Real auth + entity-level ACL MVP: password login, expiring sessions, admin-provisioned users, and per-entity `read`/`write` grants gating upload, retrieval, citations, and source assets. Design: [`docs/designs/auth_login_entity_acl_design.md`](docs/designs/auth_login_entity_acl_design.md).

Current closeout focus:

- Keep README, architecture, evaluation, smoke-test, market-evaluation, and roadmap docs aligned.
- Run one final manual demo pass across upload/process, chunk quality, retrieval test, chat, eval, jobs, and `/health`.
- Treat the 30-case golden set as a regression loop, not a market benchmark.
- Add future golden cases only from real warning/failure cases and demo gaps.

Explicitly deferred:

- Tag and ACL governance hardening.
- Storage Layer Phases 2-4: migration baseline, file-storage abstraction, object storage, deeper metrics.
- Completed document reparse/reindex.
- Doc2Query / generated chunk questions.
- Citation/evidence trust productization.
- Deployment and operations readiness.

## Roadmap Reading Guide

The sections below include both historical product-foundation plans and deferred inventory. Items that are marked complete should be treated as shipped foundation, not active scope. Items in Inventory / Deferred Ideas should stay out of the current wrap-up pass unless a concrete deployment or product requirement changes the priority.

## Product Benchmarks

### RAGFlow

RAGFlow is the closest benchmark for document-centric RAG. The useful comparison points are:

- Deep document parsing for complex PDFs, tables, scans, and mixed layouts.
- Knowledge-base-oriented ingestion workflows.
- Chunk visualization and chunk-level inspection.
- Grounded answers with traceable references.
- Self-hosted deployment experience.

The main gap for this project is not raw retrieval quality. The gap is knowledge base explainability: users cannot easily inspect how a document was parsed and chunked.

### Dify Knowledge

Dify is a stronger benchmark for product experience. The useful comparison points are:

- Simple onboarding and configuration flow.
- Knowledge retrieval testing before connecting to an application.
- Clear retrieval settings such as Top K, score threshold, rerank, and hybrid search.
- Workflow-style integration without exposing too much internal complexity.

The main gap for this project is not pipeline sophistication. The gap is productized retrieval testing: users can ask questions, but cannot easily test recall without running generation.

### Glean

Glean is a benchmark for enterprise-grade search and assistant systems. The useful comparison points are:

- Permission-aware retrieval across enterprise sources.
- Source permission sync from systems such as Drive, Slack, Jira, Confluence, GitHub, and Salesforce.
- Enterprise knowledge graph over people, teams, documents, projects, customers, tools, and activity.
- Answers generated only from content the current user is allowed to access.
- Governed references, where cited documents and assets follow the same permission model as search results.

This project should not try to copy Glean directly. Glean's design depends on enterprise connectors, identity sync, group membership, ACL propagation, and organization-scale metadata. Those are outside the current project scope.

The useful lesson is architectural: enterprise RAG should eventually treat permissions and business context as first-class retrieval constraints, not as UI-only filters.

### Vectara

Vectara is a useful benchmark for grounded generation and factual consistency. The useful comparison points are:

- Generated answers are explicitly grounded in retrieved evidence.
- Citations are treated as proof, not just links.
- Factual consistency and hallucination risk are measured as product features.
- Evaluation focuses on whether the answer is supported by the supplied context.

The main lesson for this project is that citations alone are not enough. A generated answer can cite the right documents while still making unsupported or overconfident claims. A mature RAG product should show whether the final answer is actually supported by the retrieved chunks.

## Historical Product Foundation

The following scopes describe the product foundation that led to the current system. Most of these capabilities have already been implemented or consolidated into Phase 11-14 work. Keep them as architectural context, not as a fresh execution queue.

### 1. Document Detail And Chunk Viewer

Add a document detail page focused on parsed artifacts and chunks.

Minimum scope:

- Open a document from the Documents page.
- Show parsing status, file metadata, entity name, page count if available, and processing timestamps.
- Show chunk list with content preview.
- Show chunk metadata: chunk id, page number, section/title, token or character length, table/image flags, embedding status.
- Search within chunks.
- Copy chunk text.
- Open related source asset when available.
- Navigate from a citation card to the exact chunk in the document detail page.

Optional extension:

- Highlight chunks that were retrieved for a selected query.
- Highlight chunks that were used as final answer citations.
- Show image descriptions and table chunks with distinct labels.
- Add a lightweight parsed Markdown preview.

Why this matters:

- Makes ingestion explainable.
- Helps debug bad answers.
- Demonstrates that the system is not a black box.
- Makes citation cards part of a traceable document structure instead of isolated source snippets.
- Directly improves demo quality.

### 2. General Markdown Demo Corpus

Add a broader Markdown-based demo corpus so the platform can be demonstrated without relying only on PDF parsing.

Minimum scope:

- Add `data/demo_docs/` with 12-20 AI-generated Markdown documents.
- Cover general enterprise knowledge scenarios: HR policy, reimbursement, procurement, security policy, product documentation, API limits, incident runbooks, customer support, SLA, project planning, and meeting notes.
- Include cross-document references and controlled inconsistencies, such as old policy vs new policy, FAQ vs product spec, or incident summary vs runbook.
- Update `seed_demo.py` to support Markdown demo seeding as the fast default path.
- Keep PDF demo seeding as an optional advanced path that requires MinerU.

Optional extension:

- Add a small golden set specifically for the Markdown corpus.
- Include no-answer questions and conflict-resolution questions.
- Add entity metadata files for each demo domain.

Why this matters:

- Makes the demo faster and more reliable.
- Removes MinerU as a hard dependency for first-run demos.
- Makes the product feel more general than stock-report analysis.
- Creates better test material for chunk viewing, retrieval testing, citations, and groundedness verification.

### 3. Retrieval Test Page And Strategy Summary

Add a retrieval-only test workflow, separate from chat generation. Fold the retrieval strategy summary into this page and into the existing query trace instead of creating a separate feature.

Minimum scope:

- Input a query.
- Run search without LLM answer generation.
- Display top chunks with score, source document, page, section, and retrieval path.
- Show whether results came from dense, sparse, HyDE, fallback, table expansion, or rerank.
- Support basic controls: Top K, hybrid on/off, HyDE on/off, rerank on/off.
- Show the active strategy: hybrid search, HyDE, rerank, Top K, fallback state, and current model names.

Optional extension:

- "Generate answer from these results" action.
- Compare retrieval modes side by side.
- Save retrieval test runs for evaluation.

Why this matters:

- Makes recall quality visible.
- Helps tune retrieval without spending LLM time.
- Aligns with Dify-style knowledge base testing.
- Gives evaluators a concrete way to inspect system behavior.

### 4. Multi-Entity Query Routing

Handle queries that mention multiple entities or ask across the whole corpus.

Minimum scope:

- Replace single `entity_name` routing with an entity routing result:
  - `single`
  - `multi_explicit`
  - `broad`
  - `ambiguous`
  - `none`
- For `multi_explicit`, retrieve per entity and merge results instead of using a single broad filter.
- For `broad`, retrieve globally and group evidence by entity.
- Record entity mode, selected entities, confidence, and per-entity hit counts in query trace.
- Adjust the final answer prompt for single-entity, comparison, and broad-corpus questions.

Optional extension:

- Ask a clarification question only when the entity target is genuinely ambiguous.
- Show entity distribution in the retrieval test page.
- Add regression cases to the Markdown demo golden set.

Why this matters:

- Prevents multi-entity queries from silently dropping one side of a comparison.
- Makes broad questions such as "which companies mention X" behave correctly.
- Gives retrieval testing a more realistic enterprise query surface.

### 5. Graph-Ready Metadata Layer

Add structured metadata that can later support a lightweight graph, without introducing a graph database or full GraphRAG.

Minimum scope:

- Give every document, chunk, citation, and retrieval event stable ids.
- Store document-to-chunk relationships.
- Store chunk-level entity mentions when available.
- Store query-to-retrieved-chunk events with rank, score, and retrieval stage.
- Store answer-to-citation-to-chunk relationships.

Possible relational model:

```text
Document -> has_chunk -> Chunk
Chunk -> mentions_entity -> Entity
Query -> retrieves -> Chunk
Answer -> cites -> Chunk
Entity -> appears_in -> Document
```

Why this matters:

- Supports citation-to-chunk navigation.
- Makes retrieval tests and groundedness checks easier to debug.
- Keeps the door open for multi-hop retrieval and lightweight graph features.
- Avoids prematurely adding Neo4j, GraphRAG, or a complex graph UI.

This is a supporting layer, not a standalone product feature. It should be implemented only where it directly serves chunk viewing, retrieval testing, citations, or evaluation.

### 6. Grounded Answer Verification

Add a post-generation verification layer inspired by Vectara's grounded generation and factual consistency focus.

Minimum scope:

- Extract key claims from the generated answer.
- Compare each claim against the retrieved chunks used for generation.
- Label claims as supported, partially supported, unsupported, or contradicted.
- Compute a groundedness score.
- Show the score and claim-level evidence in the answer UI.
- If evidence is weak, tell the user that the current knowledge base does not sufficiently support the answer.

Optional extension:

- Store groundedness score in query stats.
- Add unsupported-claim counts to evaluation output.
- Use groundedness score as a regression metric in golden set evaluation.
- Add a stricter mode that refuses to answer when evidence is below a threshold.

Follow-up configuration:

- Keep groundedness disabled by default in the main chat flow if latency or value is not acceptable.
- Add a query debug mode switch so groundedness, detailed retrieval traces, rerank debug, and claim checks can be enabled only when debugging.
- Add a `groundedness_warning_threshold` setting in the UI if groundedness remains useful as a diagnostic feature.
- When the threshold becomes user-configurable, make stats aggregation such as `low_groundedness_count` read the same threshold instead of using a fixed value.

Why this matters:

- Makes answer trust measurable.
- Distinguishes citation display from actual evidence support.
- Helps catch hallucinations, overreach, and weakly grounded summaries.
- Fits the current architecture without rewriting retrieval or ingestion.

Suggested pipeline placement:

```text
retrieve -> rerank -> generate -> citations -> groundedness_check
```

This should be implemented before larger enterprise features because it improves the core promise of the current product: answer questions from documents with evidence.

### 7. Constrained Multi-Hop Retrieval

Support bounded two-hop retrieval for queries where the final entities must first be discovered from evidence.

Example:

```text
Question: Which companies related to Zhang San mentioned AI investment plans?

Hop 1: retrieve evidence about Zhang San and related companies
Hop 2: retrieve AI investment evidence for each verified company
Final: group the answer by company with citations
```

Minimum scope:

- Add a planner that can classify a query as `single_hop`, `multi_entity`, or `multi_hop_entity_expansion`.
- Limit execution to two retrieval hops.
- Extract candidate entities from first-hop evidence.
- Require every expanded entity to have supporting evidence before second-hop retrieval.
- Run second-hop retrieval per verified entity.
- Show each hop in trace: hop query, discovered entities, evidence chunks, and second-hop hits.

Why this matters:

- Handles realistic enterprise questions that require entity discovery before answering.
- Uses LangGraph for controlled orchestration instead of an open-ended agent loop.
- Builds naturally on multi-entity routing and graph-ready metadata.

This should not be a free-form agent. Keep the planner constrained, the hop count bounded, and every intermediate entity evidence-backed.

### 8. Permission-Aware Retrieval

Status: **MVP shipped.** Real password login (bcrypt + expiring DB-backed sessions), admin-provisioned users, and entity-level `read`/`write` ACL now gate upload, retrieval, citation assets, and source previews. See [`docs/designs/auth_login_entity_acl_design.md`](docs/designs/auth_login_entity_acl_design.md). The remainder of this section is retained as the original scope framing; the items still outstanding (groups, chunk-level ACL, full read-path audit, deny-by-default semantics) are tracked under *Tag And ACL Governance Hardening* in Inventory / Deferred Ideas.

Add a lightweight permission model inspired by Glean, but keep it document-centric.

Minimum scope:

- Add users and groups.
- Add document-level ACL records.
- Filter retrieval by the current user's allowed documents.
- Apply the same permission check to citation assets and source previews.
- Record user id in query stats and audit logs.

Optional extension:

- Chunk-level ACL if documents contain mixed-visibility sections.
- Group inheritance for departments or project teams.
- Admin view for checking why a user can or cannot access a document.

Why this matters:

- Moves the system closer to enterprise deployment expectations.
- Prevents answers from leaking restricted content.
- Makes citations and source previews governed objects, not raw file links.

This should only be implemented after the project has a real multi-user model. With only a shared API token, permission-aware retrieval would be mostly simulated.

> Note: the real multi-user model and entity-level ACL MVP have since shipped (see status note above), so this precondition is satisfied. What remains deferred is the *hardening* layer — groups, chunk-level ACL, and full read-path audit — not the core permission loop.

### 9. Lightweight Enterprise Context Graph

Add a small context graph for explainability and business-aware retrieval. This is not full GraphRAG and not a Glean-scale enterprise graph.

Minimum scope:

- Model relationships between documents, chunks, entities, tables, images, and citations.
- Surface related documents for a selected entity.
- Show which chunks, tables, and images contributed to an answer.

Optional extension:

- Add people, teams, projects, or departments if a future connector provides that metadata.
- Use graph context as a reranking signal.
- Show a document relationship panel in the UI.

Why this matters:

- Makes the knowledge base easier to navigate.
- Helps users understand why certain evidence was retrieved.
- Creates a path toward enterprise context without overcommitting to a full knowledge graph platform.

This should come after the graph-ready metadata layer has proven useful. Do not build a graph product before the UI has clear user-facing reasons to show relationships.

## Scope Consolidation

Several ideas overlap. They should be implemented as fewer, stronger capabilities instead of many separate features.

### Merge Citation Navigation Into Chunk Viewer

Citation-to-chunk navigation should not be a separate feature. It belongs inside Document Detail And Chunk Viewer.

Why:

- Citations are only useful if users can inspect the source chunk in context.
- Chunk ids, source locations, and citation ids are the same data problem.
- A separate citation feature would duplicate UI and metadata work.

### Merge Retrieval Strategy Summary Into Retrieval Test And Trace

Do not create a standalone strategy page. Show the active strategy inside Retrieval Test Page and existing query trace.

Why:

- Users care about strategy while debugging retrieval or reading an answer.
- A separate summary page would become another passive dashboard.
- The same fields are already part of query execution: Top K, HyDE, rerank, fallback, dense/sparse path.

### Treat Graph-Ready Metadata As Infrastructure

Graph-ready metadata is in scope, but only as infrastructure for chunk viewer, retrieval test, groundedness, and later multi-hop retrieval.

Why:

- It gives the system stable ids and relationships.
- It avoids premature graph database complexity.
- It makes future graph features possible without forcing them into the current UI.

### Keep General Markdown Demo Corpus Small And Designed

The demo corpus should be generated once and committed as curated Markdown files. Do not build a document generator UI.

Why:

- The goal is a reliable demo and evaluation set, not a synthetic data product.
- Carefully designed inconsistencies and cross-references are more valuable than volume.
- Markdown keeps seeding fast and removes MinerU from the first-run path.

### Build Multi-Hop Only After Multi-Entity Routing

Constrained multi-hop retrieval depends on multi-entity routing. It should reuse the same planner and trace model.

Why:

- Multi-hop is just multi-entity retrieval where the entities are discovered in hop 1.
- Building multi-hop first would make debugging much harder.
- The same per-entity retrieval, grouping, and prompt logic can be reused.

### Defer Permission-Aware Retrieval Until There Are Real Users

Status: **moot — the MVP has shipped.** The user model and entity-level ACL are implemented, and the full sequence (user model → entity ACL → retrieval filter → governed citations) is in place. Kept here as historical context for the decision.

Permission-aware retrieval should stay in the plan, but not in the near-term build.

Why:

- A shared API token cannot express real user permissions.
- Without user/group identity, ACLs would be mostly simulated.
- The correct sequence is user model -> document ACL -> retrieval filter -> governed citations.

### Keep Lightweight Context Graph Behind Graph-Ready Metadata

Do not build a graph UI or graph retrieval before the system has enough structured relationships.

Why:

- A graph without real relationships is mostly decorative.
- Document/chunk/entity/citation edges should first prove useful in existing workflows.
- The future graph should emerge from actual metadata, not from a separate architecture push.

## Final Feature Freeze Scope

Most large roadmap items are now implemented: document/chunk inspection, Markdown demo corpus, retrieval test, multi-entity routing, retrieved chunk tracking, groundedness diagnostics, constrained multi-hop retrieval, permission-aware retrieval, and lightweight entity/document navigation.

Before feature freeze, only add product-quality features that close the enterprise loop:

```text
permissions -> retrieval audit -> quality feedback -> regression evaluation
```

Do not add new retrieval algorithms, connectors, BI, full RBAC, or graph database work in this final batch.

### 1. Query Access Audit

Goal: make every query inspectable by user, retrieval path, and accessed chunks.

Current foundation:

- `query_run_stats.user_id` exists.
- `query_run_stats.retrieved_chunks` exists.
- Evaluate records already show query stats and retrieval replay data.

Minimum scope:

- Include `user_id` in query stats record API responses.
- In the Evaluate records table, show user id / user label.
- In the retrieved chunks drawer, show document id, chunk id, rank, score, stage, and source title.
- Clearly show empty-result cases caused by ACL filtering, such as `acl_empty`.
- Admin sees all query records.
- Normal users see only their own query records.

Nice-to-have:

- Add a small user filter dropdown for admin.
- Add a badge for `status`: success, search_failed, llm_failed, client_aborted.

Out of scope:

- Full audit log export.
- Compliance retention policy.
- Cross-user analytics dashboards.

Why first:

- It reuses existing stats data.
- It verifies permission-aware retrieval from the query side, not only from the document list.
- It is the lowest-cost feature in this final batch.

### 2. Permission Audit Page

Status: **superseded by the shipped entity-ACL design.** The per-document `document_acl` model described below was retired in favor of admin-managed per-entity `read`/`write` grants with real password login. See [`docs/designs/auth_login_entity_acl_design.md`](docs/designs/auth_login_entity_acl_design.md). The body is retained as the original feature-freeze plan; the current UI is **Settings → 实体配置 (Entity Config)** for grants and **Settings → 用户管理 (User Management)** for users, not a per-document owner/read audit view.

Goal: make document permissions visible and explainable for the demo.

Current foundation:

- `users` table exists.
- `document_acl` table exists.
- Upload grants owner.
- Admin grant endpoint exists.
- Demo users exist: Admin, Alice, Bob.

Minimum scope:

- Add an admin-only permission audit API.
- Return each document with owner/read users.
- Return user list for display.
- Add a simple frontend page or settings sub-section:
  - document title
  - entity name
  - owner users
  - read users
  - cleanup/status indicator
- Reuse the existing grant endpoint for permission changes if needed.

Suggested API shape:

```text
GET /api/admin/acl/documents
-> {
  users: [{ user_id, username, role }],
  documents: [
    {
      document_id,
      filename,
      entity_name,
      status,
      cleanup_status,
      permissions: [{ user_id, username, role, permission }]
    }
  ]
}
```

Nice-to-have:

- Inline grant/revoke for Alice/Bob.
- "View as user" shortcut that switches frontend demo token.

Out of scope:

- Group ACL.
- Role editor.
- Real identity provider integration.
- Permission inheritance.

Why second:

- It completes the Step 8 story.
- It makes the Alice/Bob/Admin demo self-explanatory.
- It helps verify that document access, citation assets, and query retrieval all use the same permission model.

### 3. Answer Feedback To Golden Set Draft

Goal: capture user-visible answer quality failures and turn them into future evaluation cases.

Minimum scope:

- Add `query_feedback` table:

```sql
CREATE TABLE IF NOT EXISTS query_feedback (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    query        TEXT NOT NULL,
    answer       TEXT DEFAULT '',
    citations    TEXT DEFAULT '[]',
    user_id      TEXT DEFAULT '',
    rating       TEXT NOT NULL, -- up | down
    comment      TEXT DEFAULT '',
    created_at   TEXT NOT NULL
);
```

- Add API:

```text
POST /api/query/feedback
GET  /api/query/feedback   -- admin-only
```

- In chat UI, show thumbs up/down below each assistant answer.
- For thumbs down, allow a short optional comment.
- Store query, answer, citations, session id, user id, and rating.
- Admin can view feedback records in Evaluate or a small feedback panel.

Nice-to-have:

- "Promote to golden set draft" button that writes a JSONL draft entry or returns a copyable JSON object.
- Link feedback to retrieved chunks if available.

Out of scope:

- Automatically modifying the official golden set.
- LLM-generated expected answers.
- Feedback analytics beyond a simple list.

Why third:

- It connects product usage to evaluation.
- It gives a realistic quality-improvement loop without building a full annotation platform.
- It is useful even when no automated judge is trusted.

### 4. Relevance Tuning And Eval Regression Button

Goal: make evaluation runnable from the product UI without turning this into an experiment platform.

Minimum scope:

- Admin-only "Run Golden Set" button.
- Run the existing golden set evaluation path with the current backend settings.
- Show status: idle, running, succeeded, failed.
- Show latest summary:
  - total cases
  - pass rate
  - average score
  - failed case count
  - output file path or result id
- Keep the detailed result file as JSONL/JSON under `data/`.

Suggested implementation boundary:

- First version can call an internal service that reuses existing eval logic.
- If direct script reuse is awkward, add a thin backend runner around the same evaluation functions.
- Store only the latest run summary in SQLite or a small JSON file.

Nice-to-have:

- Show failed cases in a table.
- Compare latest run with previous run.
- Add a link from failed cases to retrieved chunks / citations.

Metric placement:

- Online query stats should only show metrics that do not require ground truth:
  - total queries
  - success / failed / aborted counts
  - failure rate
  - average latency
  - p50 latency
  - p95 latency
  - average result count
  - average rerank score
  - fallback ratio
  - average retrieved chunk count
- Golden set regression should show quality metrics that require expected answers or expected chunks:
  - Hit@5
  - Hit@10
  - citation hit rate
  - answer pass rate
  - average answer score
  - average citation score
  - average faithfulness score
  - p95 latency on the golden set
  - failed case count
- Do not mix Hit@K or citation hit rate into normal online stats, because ordinary user queries do not have expected chunks.

Out of scope:

- Parameter sweep.
- A/B testing.
- Multi-dataset management.
- Background job framework beyond one in-process task.
- Scheduled evaluation.

Why last:

- It has the largest blast radius.
- It touches scripts, API, long-running task state, and UI.
- It should reuse query audit and feedback data rather than creating another disconnected page.

### Final Batch Execution Order

1. Query Access Audit.
2. Permission Audit Page.
3. Answer Feedback To Golden Set Draft.
4. Relevance Tuning And Eval Regression Button.

Acceptance criteria for the final batch:

- Admin can explain what each user can access.
- A query record shows who asked, what was retrieved, and which chunks were used.
- A bad answer can be captured as structured feedback.
- The golden set can be rerun from the UI and the latest result is visible.

After these four are complete, stop adding features and move to README screenshots, demo script, and final cleanup.

## Post-Freeze Product Foundation

Phases 0-10 are now treated as completed product foundation. This includes query flavor control, controlled entity fallback, dynamic retrieval budget, small-to-big context, query expansion, flavor-level metrics, alias and keyword enrichment, user-facing terminology, chunk search enrichment, and tag governance.

Before adding more retrieval algorithms, the project should strengthen the product foundation around evaluation, observability, ingestion quality, and background-job reliability.

### Phase 11: Golden Set Evaluation Loop And Fast Eval Modes

Detailed scope: [`docs/archive/completed/phase11_eval_loop.md`](docs/archive/completed/phase11_eval_loop.md)

Status: complete. Current product semantics are three run modes
(`retrieval_only`, `answer_lite`, `full`) plus a smoke-case subset filter.
The backend still accepts `quick` as a compatibility path, but the UI should
present 冒烟集 as case selection rather than a fourth mode.

Goal: turn the current 30-case golden set from a slow smoke test into a practical evaluation loop that can guide retrieval changes.

Thirty cases are not enough for final confidence, but they are enough to build the evaluation machinery. The target is an evaluation pyramid:

```text
smoke subset      5-8 representative cases, selected before commit
retrieval-only    all cases, no answer generation, no judge
answer-lite       selected cases, generation on, judge off or cached
full regression   all cases, generation + judge, nightly or release gate
```

Why this comes before more retrieval work:

- Later phases need a fast way to prove whether recall improved or only latency increased.
- Full answer judging is too slow and too expensive to run after every small retrieval change.
- Retrieval failures should be separated from generation, citation, and judge failures.
- A small golden set becomes useful only when failures are categorized and replayable.

Minimum scope:

- Add `eval_mode` to the backend eval runner, admin eval API, and UI:
  - `quick`
  - `retrieval_only`
  - `answer_lite`
  - `full`
- Add a deterministic quick subset, either by explicit `case_ids` or a `quick: true` field in JSONL.
- Add retrieval-only execution that runs the search pipeline and returns top chunks without LLM answer generation.
- Record retrieval metrics per case:
  - `Hit@5`
  - `Hit@10`
  - expected document/chunk coverage
  - top retrieved documents/chunks
  - retrieval flavor
  - retrieval path
  - rerank score
  - retrieval latency
- Keep answer metrics for answer-capable modes:
  - answer pass/fail
  - expected point coverage
  - citation hit rate
  - no-answer correctness
  - groundedness or faithfulness score when available
- Store run summaries with mode, flavor, case count, pass rate, retrieval metrics, answer metrics, p50/p95 latency, and output path.

Recommended implementation:

1. Extend the existing eval request shape.
   - Add `mode: "quick" | "retrieval_only" | "answer_lite" | "full"`.
   - Keep `case_ids`, `flavor`, `limit`, and `case_timeout_sec`.
   - Default UI mode should be `quick` or `retrieval_only`, not full judge.

2. Add a retrieval-only backend path.
   - Prefer calling the shared search pipeline directly instead of opening a chat stream and aborting it.
   - Return normalized hits, citations candidates, trace, timing, and retrieval path.
   - Do not call answer generation or LLM judge in this mode.

3. Add quick case selection.
   - Mark 5-8 representative cases as quick.
   - Include at least one exact lookup, one recall-heavy case, one multi-entity case, one no-answer case, and one permission-sensitive case if ACL is enabled.
   - Keep quick cases stable so regressions are meaningful.

4. Add judge caching.
   - Cache judge output by `(case_id, normalized_answer, expected_answer, judge_model, rubric_version)`.
   - Reuse cached judge results in `answer_lite` and `full` when the answer did not change.
   - Do not cache retrieval metrics; those should reflect the current pipeline.

5. Add limited concurrency.
   - Run retrieval-only cases concurrently with a small cap.
   - Keep answer generation and judge concurrency lower to avoid provider throttling and cost spikes.
   - Record timeout cases explicitly instead of letting the whole run fail.

6. Add baseline comparison.
   - Store the latest accepted baseline summary.
   - Compare current run against baseline by mode and flavor.
   - Show deltas for `Hit@10`, citation hit rate, answer pass rate, p95 latency, and timeout count.

Evaluation data model additions:

```json
{
  "id": "recall_agg_001",
  "question": "...",
  "quick": true,
  "slices": ["recall", "amount_threshold"],
  "expected_docs": ["12_年度培训计划_2026", "08_供应商管理制度"],
  "expected_chunk_keys": ["..."],
  "expected_points": ["..."],
  "expected_behavior": "answer",
  "failure_category": ""
}
```

Failure categories:

```text
retrieval_miss
rerank_drop
context_loss
citation_miss
answer_unsupported
answer_incomplete
no_answer_wrong
timeout
judge_uncertain
```

Acceptance criteria:

- Developers can run a fast mode before committing retrieval changes.
- Retrieval-only results identify whether a case failed before generation.
- Full 30-case evaluation is no longer the only useful signal.
- Every failed case has enough trace data to explain the failure category.
- Future golden set growth to 80-150 cases does not make day-to-day evaluation unusable.

Work estimate:

- MVP: 2-3 days.
  - Add eval modes.
  - Add retrieval-only runner.
  - Add quick subset.
  - Show mode summaries.
- Practical version: 5-7 days.
  - Add UI selector.
  - Add limited concurrency.
  - Add judge cache.
  - Add grouped failure report and baseline delta.
- Productized version: 8-12 days.
  - Add result comparison UI.
  - Add case management.
  - Add failure categorization workflow.
  - Add scheduled/nightly run support.

Not doing in Phase 11:

- No large annotation platform.
- No automatic golden set rewriting.
- No parameter sweep framework.
- No A/B testing system.
- No new retrieval algorithm until the faster eval loop is working.

### Phase 12: Query Observability And Latency/Cost Profile

Goal: make every query explainable by stage timing, retrieval path, token usage, fallback behavior, and failure reason.

This is the highest-priority foundation after Phase 11. The query stack is now powerful but complex. Without stage-level observability, it is hard to tell whether a change improved quality, moved latency, increased cost, or only made traces noisier.

Minimum scope:

- Record stage-level timing for:
  - query rewrite
  - HyDE
  - query expansion
  - dense/sparse search
  - RRF merge
  - table expansion
  - rerank
  - context expansion
  - multi-hop discovery
  - prompt build
  - answer generation
  - groundedness / judge when enabled
- Record resolved query settings:
  - retrieval flavor
  - strict evidence
  - entity mode
  - fallback policy and fallback result
  - retrieval budget
  - search limit and rerank candidate count
- Record result-shape metrics:
  - retrieved chunk count
  - reranked chunk count
  - final context chunk count
  - citation count
  - average / max rerank score
  - empty-result reason
- Record LLM cost signals where available:
  - prompt tokens
  - completion tokens
  - total tokens
  - model name
  - estimated cost if pricing config exists
- Add p50/p95 summaries grouped by retrieval flavor, success/error status, and endpoint.

Suggested data shape:

```json
{
  "query_id": "qr_...",
  "retrieval_flavor": "balanced",
  "strict_evidence": false,
  "entity_mode": "single",
  "timings_ms": {
    "rewrite": 120,
    "search": 310,
    "rerank": 480,
    "context_expand": 45,
    "generate": 2100
  },
  "token_usage": {
    "model": "qwen-plus",
    "prompt_tokens": 3200,
    "completion_tokens": 420
  },
  "result_shape": {
    "retrieved_chunks": 24,
    "reranked_chunks": 12,
    "final_context_chunks": 5,
    "citations": 4
  },
  "fallback_info": {
    "used": false,
    "blocked": false,
    "reason": ""
  }
}
```

Implementation notes:

- Reuse existing `query_run_stats` rather than creating a separate analytics system.
- Keep raw per-query traces available for debugging, but add compact summary fields for list views.
- Add a small admin view or existing stats panel section for latency and cost summaries.
- Do not introduce OpenTelemetry/APM in this phase unless the local stats model is already clear.

Acceptance criteria:

- A slow query can be attributed to specific stages.
- A quality regression can be inspected with rerank-before/after and fallback data.
- Admin can compare p50/p95 latency by retrieval flavor.
- Token usage and model names are visible for cost investigation.
- Empty result, timeout, no-answer, and fallback cases are classified.

### Phase 13: Document Parsing And Chunk Quality Governance

Execution doc: [`docs/archive/completed/phase13_chunk_quality.md`](docs/archive/completed/phase13_chunk_quality.md).

Goal: make ingestion quality visible and correctable before retrieval tuning starts blaming search for bad chunks.

Query quality depends heavily on source artifacts. If parsing drops table structure, creates oversized chunks, loses section titles, duplicates content, or fails image/table descriptions, retrieval will look weak even when search logic is sound.

Minimum scope:

- Add chunk quality metrics during ingestion:
  - chunk count per document
  - min / max / average chunk length
  - chunks without section/title
  - chunks over size threshold
  - chunks under size threshold
  - duplicate or near-duplicate chunks
  - table chunks without table metadata
  - image references without description or asset path
  - chunks with empty or low-information content
- Persist quality reports under parsed artifacts, for example:

```text
parsed/{document_id}/chunk_quality.json
```

- Surface quality status in document detail:
  - good
  - warning
  - failed
  - needs reparse / reindex
- Add parsing and chunking version metadata:
  - parser name/version
  - chunker version
  - enrichment profile
  - schema/index version
  - processed_at
- Add reparse/reindex history so repeated processing is auditable.
- Add a compact chunk diff report for reprocessed documents:
  - added chunks
  - removed chunks
  - changed chunk count
  - changed section coverage

Suggested quality report shape:

```json
{
  "document_id": "doc_...",
  "status": "warning",
  "parser_version": "markdown_v2",
  "chunker_version": "semantic_v3",
  "chunk_count": 42,
  "warnings": [
    {"type": "oversized_chunk", "count": 2},
    {"type": "missing_section_title", "count": 5},
    {"type": "table_without_metadata", "count": 1}
  ]
}
```

Implementation notes:

- Keep this deterministic; do not use LLM quality scoring in the first version.
- Start with warning metrics and visibility, not automatic chunk rewriting.
- Reuse document detail and admin document APIs instead of creating a separate quality product.
- Connect quality warnings to retrieval failures only through links/traces, not automatic blame.

Acceptance criteria:

- Admin can see whether a document produced healthy chunks.
- A bad answer can be traced back to either retrieval behavior or suspicious source chunks.
- Reprocessing a document records parser/chunker versions and changed artifact shape.
- Demo documents have visible quality status with no noisy false alarms.

### Phase 14: Background Job Reliability

Goal: make ingestion, reindex, cleanup, and evaluation run as trackable jobs instead of one-off requests.

The project now has several long-running operations. They need a shared job model so failures, retries, progress, and cancellation are consistent.

Status: P1 complete. P2 deferred.

P1 completed scope:

- Add a `jobs` table:

```text
job_id
job_type
status               queued | running | succeeded | failed | canceled
resource_type        document | eval | cleanup | index
resource_id
progress_current
progress_total
message
error_code
error_detail
attempt_count
created_by
created_at
started_at
finished_at
updated_at
```

Supported job types in P1:

- document ingestion
- golden-set eval run

Completed behavior:

- Job creation returns a `job_id`.
- Job status can be polled from the API.
- Failed jobs store a clear error code and message.
- Startup can mark stale `running` jobs as failed/recoverable.
- Document status and job status do not contradict each other.
- Admin can inspect recent document/eval jobs in Settings.

Deferred P2:

- job metadata and lineage for reliable retry/reparse context
- explicit job retry
- safe cancellation where truthful
- completed document reparse/reindex
- document cleanup jobs
- worker extraction readiness

Completed document reparse/reindex is the highest-value deferred item, especially
after chunk quality governance, but it is not part of Phase 14 P1.

Implementation notes:

- Keep the first implementation in-process; do not add Celery/RQ unless needed.
- Design the DB/API shape so a real worker can replace the in-process runner later.
- Make operations idempotent where possible, especially ingestion and reindex.
- Preserve existing endpoints by wrapping their long-running work in job creation.
- Add admin UI status chips and a lightweight job detail drawer.

Acceptance criteria:

- Admin can see current and recent long-running jobs.
- Failed ingestion/eval jobs are diagnosable without reading backend logs.
- Retrying a failed document job does not duplicate vectors or leave inconsistent document status.
- Eval runs no longer depend on a fragile long request lifecycle.

## Inventory / Deferred Ideas

Items in this inventory are explicitly not part of the current execution pass. They should not be started unless the active phases prove a concrete need.

### Section Probe Retrieval Experiment [Deferred / Not Doing Now]

Goal: test a coarse-to-fine retrieval path for long documents and long sections. Section probes may help when a whole section is relevant to the query but individual chunks are too local or too weakly worded to retrieve directly.

Status: deferred. Do not start this during the current pass. Reconsider only if Phase 11 and Phase 13 show repeated, measurable long-section recall failures that existing enrichment and search behavior cannot solve.

If resumed:

- Use section-level probes only.
- Keep probes out of final answer context.
- Use probes only to select candidate document/section scopes.
- Keep citations pointing to source chunks.
- Enable only for `recall`.
- Validate with recall slice, citation hit rate, and p95 latency.

### Doc2Query / Chunk Question Generation [Deferred / Not Doing Now]

Goal: generate answerable questions per chunk and index them in a companion collection as a recall bridge.

Status: deferred. Do not start this during the current pass. Reconsider only if the active phases show repeated, measurable natural-question recall gaps that existing enrichment, query expansion, rerank, and chunk-quality fixes cannot solve.

Minimum scope:

- For each text chunk, generate 3-5 diverse questions that the chunk can answer.
- Store generated questions as parsed artifacts and in a companion index, not inside the original chunk `content`.
- Retrieve against both original chunk content and generated questions.
- Fuse content-search and question-search results with RRF or the existing merge path.
- Show whether a hit came from original content or generated questions in retrieval test and trace.

Recommended implementation:

- Keep original evidence clean. Do not append generated questions to `content`, because `content` is used for BM25, citations, chunk viewer, and final prompt context.
- Add a companion Milvus collection such as `general_doc2query`.
- Store each generated question as a separate row linked back to the original chunk by `parent_chunk_id`.
- Search the companion collection only as a recall bridge; the final answer must still use the original chunk content.

Suggested companion collection fields:

```text
question_id        INT64 auto id
parent_chunk_id    INT64
document_id        VARCHAR
entity_name        VARCHAR
file_title         VARCHAR
section_title      VARCHAR
page               INT64
part               INT8
question           VARCHAR
question_type      VARCHAR
original_content   VARCHAR
dense              FLOAT_VECTOR
sparse             SPARSE_FLOAT_VECTOR from question
```

Ingestion flow:

```text
chunk
  -> generate_chunk_questions
  -> embed original chunks
  -> save original chunks to general_documents
  -> save generated questions to general_doc2query
```

Query flow:

```text
normal_search(query)
doc2query_search(query)
merge_by_parent_chunk_id()
rerank(original_chunk_content)
generate answer from original chunks only
```

The returned retrieval result may include debug fields such as:

```text
retrieval_stage: doc2query
matched_question: "员工差旅餐费补贴标准是多少？"
```

but prompt construction and citations must use the original chunk content and original chunk id.

Rollout plan:

- First expose Doc2Query only in retrieval test.
- Then enable it for `recall` flavor.
- Do not enable it by default in `balanced` until eval shows clear improvement.

Suggested config:

```text
use_doc2query: false
doc2query_questions_per_chunk: 3
doc2query_max_chunk_chars: 1800
doc2query_model: CHAT_MODEL
```

Validation:

- Compare `Hit@5`, `Hit@10`, citation hit rate, answer pass rate, and retrieval latency.
- Inspect matched generated questions in retrieval test for noise.
- Confirm citations and document detail views remain based on original chunks only.

Why this matters:

- User questions often do not share wording with enterprise documents.
- Generated questions turn declarative policy text into query-shaped retrieval targets.
- This is especially useful for HR policy, reimbursement, procurement, security policy, and product docs.

Value / cost:

- Value: 5/5.
- Cost: 3/5.

Risk:

- Generated questions can overfit or introduce unsupported intents.
- Keep generated questions strictly answerable from the chunk and inspectable in the chunk viewer.

### Citation / Evidence Trust Productization [Deferred / Not Doing Now]

Goal: turn citation validation and groundedness into a user-facing trust workflow.

Status: inventory only. Do not start this until Phase 11 proves which answer-quality failures are common enough to justify product work.

Potential scope:

- Map key answer claims to supporting citations.
- Show whether each claim is supported, weakly supported, unsupported, or contradicted.
- Make unsupported answer spans visible in the UI.
- Distinguish "citation exists" from "citation supports this claim."
- Add a compact evidence confidence summary for users.

Why deferred:

- The current priority is developer/operator visibility, not a larger user-facing trust UX.
- This can become expensive and noisy without a reliable eval loop and observed failure categories.

### Tag And ACL Governance Hardening [Deferred / Not Doing Now]

Goal: turn the current tag and ACL foundations into trustworthy data governance
instead of demo-level metadata.

Status: inventory only. Do not start this during the current pass. The project is
currently in feature-freeze/polish mode, and this work should only resume if the
next objective is a real multi-user deployment or long-lived knowledge-base
governance.

Current assessment:

- Structured tags already have a useful foundation: registry, overrides,
  preview, metrics, chunk metadata, and UI exposure.
- Tags are not yet a fully stable data contract because tag provenance,
  rule/version history, document-level profile tagging, and eval slices are not
  first-class.
- ACL MVP has shipped: real password login, expiring sessions,
  admin-provisioned users, and per-entity `read`/`write` grants gating upload,
  retrieval, citation assets, and source previews, with an admin-managed grant
  view and bootstrap admin bypass.
- ACL is the higher-risk area because mistakes can leak restricted content.
  What remains deferred is the hardening layer: group ACL, deny-by-default
  semantics, chunk-level ACL, alias expansion at the ACL read side, full
  read-path enforcement audit, and ACL regression cases.

If resumed, minimum tag-governance scope:

- Treat the structured tag registry as the only source of truth.
- Keep unknown extracted phrases in `keywords`; do not promote them to tags.
- Store tag rule/profile/version metadata in processed artifacts.
- Record why a chunk received a tag: matched rule, evidence terms, and profile.
- Add document-level tags/profile such as policy, runbook, FAQ, API docs,
  security, procurement, HR, or finance.
- Add golden-set slices by tag, such as amount threshold, approval rule, deadline,
  and security incident cases.

If resumed, minimum ACL-governance scope:

- Make deny-by-default semantics explicit for non-admin users.
- Add group ACL support before trying to manage many users manually.
- Audit every read path for permission enforcement:
  - document list
  - document detail
  - chunk API
  - citation-to-chunk navigation
  - retrieval test
  - query stats/detail
  - feedback records
  - eval case details containing retrieved chunks
- Apply citation/source visibility checks after answer generation, not only
  during retrieval.
- Add query observability fields for ACL behavior, such as `acl_mode`,
  `allowed_doc_count`, and `acl_empty`.
- Add ACL regression cases for admin, Alice, Bob, no-access, retrieval-only,
  chat, document detail, and citation detail.

Why deferred:

- Group ACL, source inheritance, audit trails, and full read-path enforcement are
  real governance work, not small UI tweaks.
- The current project direction is to stop adding features and consolidate the
  product story.
- Tag mistakes primarily hurt recall and explainability; ACL mistakes are
  security incidents, so ACL work must be done deliberately when the project is
  ready for multi-user deployment.

### Deployment And Operations Readiness [Deferred / Not Doing Now]

Goal: improve production readiness around health checks, configuration validation, backups, quotas, and operational guardrails.

Status: inventory only. Do not start this during the current pass unless deployment becomes the main objective.

Potential scope:

- Startup configuration validation.
- Health checks for API, database, Milvus, file storage, model provider, and rerank provider.
- Backup/restore documentation for SQLite, parsed artifacts, uploaded files, and Milvus collections.
- Secret-management guidance.
- Rate limit and quota dashboards.
- Provider availability and cost guardrails.
- Basic deployment runbook.

Why deferred:

- The project is still optimizing product/query foundations.
- Full operations hardening matters most when a real deployment target is selected.

## Not Recommended For This Project

Avoid these unless the project is deliberately repositioned as a full platform:

- ChatBI integration inside this codebase.
- Agent workflow canvas.
- Confluence, Notion, Google Drive, or S3 connectors.
- Manual chunk editing.
- GraphRAG or knowledge graph features.
- Multiple knowledge base routing.

Defer these until there is a real enterprise use case:

- Multi-tenant organization management.
- Complex RBAC.
- Full Glean-style enterprise connector platform.
- Full enterprise knowledge graph over people, teams, systems, and activity.

These are legitimate product directions, but they increase scope faster than they improve the current Enterprise RAG story.

## Suggested Execution Order

Completed major roadmap items and query-flavor phases should now be treated as product foundation, not as open-ended scope.

For previous retrieval-quality work, use the executable roadmap in
[`docs/archive/historical/query_flavor_roadmap.md`](docs/archive/historical/query_flavor_roadmap.md) as historical
context. Phases 0-10 are complete.

Completed execution:

1. Phase 11: Golden Set Evaluation Loop And Fast Eval Modes.
2. Phase 12: Query Observability And Latency/Cost Profile.
3. Phase 13: Document Parsing And Chunk Quality Governance.
4. Phase 14: Background Job Reliability P1.
5. Storage Layer Maturity Phase 1.

Current wrap-up order:

1. Update README and docs to show the final product story.
2. Run one final manual smoke pass.
3. Capture any final warning cases as future golden-set candidates.
4. Keep Inventory / Deferred Ideas out of the current pass.
5. Stop feature work unless a blocker appears during final validation.

## Success Criteria

The project should answer three product questions clearly:

- What documents are in the knowledge base?
- How were those documents parsed and chunked?
- Which chunks were retrieved before the final answer was generated?

If those are visible in the UI, the project moves from a working RAG demo to a mature, inspectable RAG product.
