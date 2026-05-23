# Evaluation & Observability

## Golden Set Evaluation

The evaluation system measures answer quality, citation accuracy, and refusal correctness against a known test set.

### Running

```bash
cd backend
python scripts/eval_golden_set.py \
  --golden-set ../data/stock_reports_v2.jsonl \
  --api-base http://127.0.0.1:8010/api \
  --judge \
  --output ../data/stock_reports_v2_results.jsonl
```

### Test Types

| Type | Count | What It Tests |
|---|---|---|
| `rule` | 10 | Numeric extraction accuracy, required/optional keyword presence, citation recall |
| `llm_judge` | 5 | Complex reasoning quality against expected points, citation recall |
| `no_answer` | 2 | Correct refusal when answer is not in corpus |

### Scoring Axes

Each test case produces scores on multiple axes:

| Axis | Description |
|---|---|
| `answer_score` | Numeric tolerance + keyword match (rule) or LLM judge rating (llm_judge) |
| `citation_score` | Fraction of expected documents found in citations |
| `faithfulness` | Whether answer is grounded in cited sources (LLM judge only) |

### Input Format (JSONL)

```json
{
  "id": "q1",
  "question": "中芯国际2025年Q1营收是多少？",
  "eval_type": "rule",
  "numeric_expectations": [{"field": "revenue", "value": 227.2, "tolerance": 5}],
  "must_have": ["227"],
  "nice_to_have": ["亿元"],
  "expected_documents": ["华泰证券"],
  "min_expected_citations": 1
}
```

| Field | Purpose |
|---|---|
| `numeric_expectations` | Numeric value + tolerance for rule cases |
| `must_have` / `nice_to_have` | Required and optional answer keywords |
| `expected_documents` | Expected citation source substrings |
| `min_expected_citations` | Minimum number of source matches |
| `expected_points` | Checklist for LLM judge cases |
| `no_answer_type` | Refusal scenario type |

### Output

| File | Content |
|---|---|
| `*_results.jsonl` | Per-question: answer, citations, scores, trace, rerank debug |
| `*_summary.json` | Overall score, pass rate, per-type breakdown, low-score cases |

### Verdict Thresholds

| Verdict | Meaning |
|---|---|
| `pass` | Score ≥ 0.7 |
| `warn` | Score 0.4–0.7, answer usable but needs review |
| `fail` | Score < 0.4 |

### Current Baseline

```text
Questions: 17 (rule=10, llm_judge=5, no_answer=2)
Overall:   avg=0.963, pass_rate=100%
Rule:      avg=0.968, pass_rate=100%
LLM judge: avg=0.939, pass_rate=100%
No-answer: avg=1.000, pass_rate=100%
```

Rerun after changes to chunking, retrieval, rerank, or prompt construction. Flag regressions where overall score drops below baseline or no-answer cases fail.

---

## Query Trace

Each SSE streaming response includes structured trace events:

| Event | Content |
|---|---|
| `message_start` | Session info, query text |
| `retrieval_step` | Search mode, rewritten query, entity filter, hit count |
| `rerank_results` | Top N chunks with rerank scores |
| `citation_result` | Selected citations with source metadata and image paths |
| `trace` | Full latency breakdown per stage |
| `message_end` | Final status, total latency |

### Latency Breakdown

The `trace` event reports timing for each pipeline stage:

| Stage | What It Measures |
|---|---|
| `entity_confirm` | Entity detection + confirmation |
| `rewrite` | Query rewriting |
| `search` | Vector + BM25 search |
| `hyde` | Hypothetical document search (when used) |
| `fusion` | RRF fusion |
| `rerank` | LLM cross-encoder reranking |
| `generate` | LLM answer generation |
| `validate_citations` | Citation source validation |

---

## Query Statistics

The Evaluate page aggregates per-query stats for monitoring retrieval quality over time.

### Aggregate Metrics

| Metric | Description |
|---|---|
| Total queries | Count across all statuses |
| Failure rate | `(search_failed + llm_failed + client_aborted) / total` |
| Avg rerank score | Mean rerank score across successful queries |
| Avg result count | Mean retrieved documents per query |
| Fallback count | Queries where entity filter fell back to broad search |
| Fallback ratio | Fallback count / successful queries |

### Query Statuses

| Status | Meaning |
|---|---|
| `success` | Complete answer with citations |
| `search_failed` | Retrieval pipeline error |
| `llm_failed` | LLM generation error |
| `client_aborted` | User disconnected mid-stream |

### Records Table

Each query record includes: timestamp, query text, search mode, result count, rerank avg/top scores, total latency, and status.

---

## Error Classification

All errors are classified into structured codes for debugging and alerting:

| Code | Source | User Hint |
|---|---|---|
| `MINERU_API_ERROR` | MinerU API failure | "文档解析服务异常，请稍后重试" |
| `EMBEDDING_ERROR` | DashScope embedding failure | "向量化服务异常，请稍后重试" |
| `MILVUS_ERROR` | Milvus connection/query failure | "向量数据库异常，请检查 Milvus 连接" |
| `LLM_ERROR` | DashScope LLM failure | "大模型服务异常，请稍后重试" |
| `NO_CONTEXT_FOUND` | Retrieval returned nothing | "未找到相关内容，请尝试换个表述或上传更多文档" |
| `UNKNOWN_ERROR` | Unhandled exception | "未知错误，请查看详情或联系管理员" |

Error classification happens in `backend/app/errors.py` — it inspects exception type and message to select the appropriate code. Each code has a Chinese user-facing hint displayed in the frontend.
