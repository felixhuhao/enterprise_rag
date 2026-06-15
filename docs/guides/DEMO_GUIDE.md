# Demo Guide

This guide is for producing project screenshots, short recordings, and manual demo passes. It is intentionally presentation-oriented; setup commands live in [DEVELOPMENT.md](DEVELOPMENT.md).

## Demo Goal

Show that Enterprise RAG is not just a chat UI over documents. The demo should make four qualities visible:

1. Documents are parsed and chunked into inspectable artifacts.
2. Retrieval behavior can be tested before answer generation.
3. Answers are grounded in citations and strict evidence policy.
4. Quality is measurable through evaluation and observability.

## Recommended Demo Flow

1. **Documents**
   - Show completed enterprise demo documents.
   - Open one document detail page.
   - Highlight chunk quality status, chunk warnings, table chunks, and image references if present.

2. **Retrieval Test**
   - Run a precise lookup.
   - Show Top K chunks, scores, retrieval paths, active strategy, and rerank details.
   - Run a recall query and show query expansion or broader retrieval behavior.

3. **Query Chat**
   - Ask a normal policy question and show streaming answer with citations.
   - Ask a strict-evidence missing-fact question and show conservative refusal.
   - Show citation details and source trace.

4. **Evaluation**
   - Open the baseline evaluation panel.
   - Run a small smoke subset or show a completed run.
   - Highlight retrieval-only metrics, answer-lite/full modes, failure categories, and accepted-baseline delta.

5. **Observability**
   - Open query records.
   - Show latency breakdown, token usage, resolved settings, fallback details, and result shape.

6. **Background Jobs**
   - Show document ingestion or evaluation jobs.
   - Highlight status, progress, timestamps, and error visibility.

## Screenshot Checklist

Save final assets under `docs/images/`.

### README Featured Images

These are the strongest images for the repository landing page.

| File | View | Purpose |
|---|---|---|
| [`query-balanced-answer.png`](../images/query-balanced-answer.png) | Query Chat | Citation-grounded cross-document answer. |
| [`query-discovery-multihop.png`](../images/query-discovery-multihop.png) | Query Chat | Multi-hop discovery with visible hop trace. |
| [`query-strict-evidence.png`](../images/query-strict-evidence.png) | Query Chat | Strict evidence answer that avoids inventing an unsupported fact. |
| [`retrieval-test-recall.png`](../images/retrieval-test-recall.png) | Retrieval Test | Query expansion, retrieval trace, Top K chunks, scores, and tags. |
| [`document-chunks-quality.png`](../images/document-chunks-quality.png) | Document Detail | Chunk types, table chunks, quality status, and content previews. |
| [`eval-baseline-summary.png`](../images/eval-baseline-summary.png) | Quality Center | Run-level metrics, failure categories, per-strategy breakdown, and baseline context. |
| [`eval-case-detail.png`](../images/eval-case-detail.png) | Quality Center | Case-level diagnosis: expected evidence, missing citation, answer, retrieval result. |

README should stay compact. Keep secondary screenshots linked from this guide.

### Full Screenshot Gallery

Query Chat:

| File | Purpose |
|---|---|
| [`query-balanced-answer.png`](../images/query-balanced-answer.png) | Balanced answer with citations and a structured comparison. |
| [`query-exact-trace.png`](../images/query-exact-trace.png) | Exact lookup for a numeric policy fact with retrieval timing. |
| [`query-recall-expansion.png`](../images/query-recall-expansion.png) | Recall mode with expanded queries and broader retrieval. |
| [`query-discovery-multihop.png`](../images/query-discovery-multihop.png) | Discovery mode with multi-hop trace. |
| [`query-strict-evidence.png`](../images/query-strict-evidence.png) | Strict evidence answer that avoids inventing an unsupported daily API cap. |

Documents and chunks:

| File | Purpose |
|---|---|
| [`documents-list.png`](../images/documents-list.png) | Completed enterprise corpus with status and chunk counts. |
| [`document-chunks-quality.png`](../images/document-chunks-quality.png) | Chunk inspection with text/table chunk types and quality metadata. |

Retrieval Test:

| File | Purpose |
|---|---|
| [`retrieval-test-recall.png`](../images/retrieval-test-recall.png) | Recall retrieval test with query expansion and Top K chunks. |
| [`retrieval-test-balanced.png`](../images/retrieval-test-balanced.png) | Balanced retrieval test with budget, models, timings, and scores. |

Quality Center and evaluation:

| File | Purpose |
|---|---|
| [`quality-center-overview.png`](../images/quality-center-overview.png) | Quality Center navigation and high-level evaluation area. |
| [`eval-suite-setup.png`](../images/eval-suite-setup.png) | Golden-set mode, subset, smoke-set, and case enablement controls. |
| [`eval-run-progress.png`](../images/eval-run-progress.png) | Active evaluation run progress. |
| [`eval-baseline-summary.png`](../images/eval-baseline-summary.png) | Completed full run summary with metrics and failure categories. |
| [`eval-case-detail.png`](../images/eval-case-detail.png) | Full case-level diagnosis. |
| [`eval-answer-lite-summary.png`](../images/eval-answer-lite-summary.png) | Answer-lite summary over a small slice. |
| [`eval-retrieval-only-summary.png`](../images/eval-retrieval-only-summary.png) | Retrieval-only summary grouped by strategy. |
| [`eval-run-detail.png`](../images/eval-run-detail.png) | Earlier compact run detail screenshot; kept as supplemental material. |

Operations and governance:

| File | Purpose |
|---|---|
| [`system-status-jobs.png`](../images/system-status-jobs.png) | System status, model configuration, Milvus/SQLite state, and background jobs. |
| [`settings-strategy-tuning.png`](../images/settings-strategy-tuning.png) | Strategy tuning panel with retrieval budgets and enabled stages. |
| [`settings-tag-governance.png`](../images/settings-tag-governance.png) | Structured tag governance with hit counts. |
| [`access-user-management.png`](../images/access-user-management.png) | Admin user management: accounts, roles, password reset, and delete actions. |
| [`access-entity-management.png`](../images/access-entity-management.png) | Entity-level access management: per-entity `read`/`write` grants. |

## Demo Queries

| Scenario | Query | Suggested Strategy |
|---|---|---|
| Clause / amount lookup | `星辰科技的住宿标准是多少？` | 精确查找 |
| Vague recall | `电脑丢了应该怎么处理？` | 全面查找 |
| Cross-document synthesis | `星辰科技的安全事件报告和运维故障响应有什么关联和区别？` | 标准问答 |
| Multi-hop discovery | `API v1什么时候下线？迁移指南由谁负责？这个人还负责什么工作？` | 关联查找 |
| Strict evidence / missing fact | `星辰科技的API日调用量上限是多少？` with “仅基于资料回答” enabled | 标准问答 |

## Recording Outline

Target length: 90-150 seconds.

Suggested sequence:

```text
0:00  Documents page: completed corpus and job status
0:15  Document detail: chunk quality and table/image-aware chunks
0:35  Retrieval test: Top K and retrieval path trace
0:55  Chat: answer with citations
1:15  Strict evidence: unsupported daily API cap refusal
1:35  Evaluation panel: baseline metrics and failure categories
1:55  Observability: latency breakdown and resolved retrieval settings
```

Keep the recording focused on product behavior. Avoid showing `.env`, terminal logs, or setup steps unless the clip is specifically for development documentation.

## Screenshot Notes

- Use the default enterprise Markdown corpus.
- Prefer a clean browser viewport around 1440px wide.
- Hide browser bookmarks and unrelated tabs.
- Make sure the selected user filter is not visually confusing.
- Prefer completed runs over in-progress states, except for the jobs screenshot.
- If a screenshot contains a known warning case, make the warning reason visible.

## README Media Plan

README currently uses seven large screenshots:

- `docs/images/query-balanced-answer.png`
- `docs/images/query-discovery-multihop.png`
- `docs/images/query-strict-evidence.png`
- `docs/images/retrieval-test-recall.png`
- `docs/images/document-chunks-quality.png`
- `docs/images/eval-baseline-summary.png`
- `docs/images/eval-case-detail.png`

Avoid adding more large images to README unless one of these is replaced. Put the full gallery in this guide.
