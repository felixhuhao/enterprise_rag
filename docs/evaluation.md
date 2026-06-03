# Evaluation & Observability

The project uses an enterprise baseline test set to catch regressions in retrieval, citation quality, no-answer behavior, and multi-step synthesis.

## Baseline Test Set

Primary file:

```text
data/challenge_golden_set_v1.jsonl
```

The set is built around the default Markdown enterprise corpus in `data/enterprise_docs`.
Cases are grouped by retrieval intent:

| Slice | UI Strategy | Internal Flavor | What It Tests |
|---|---|---|---|
| `balanced` | 标准问答 | `balanced` | Normal Q&A, cross-document synthesis, consistency checks |
| `exact` | 精确查找 | `exact` | Precise clauses, numeric thresholds, policy source lookup |
| `recall` | 全面查找 | `recall` | Vague questions, synonyms, query expansion recall |
| `discovery` | 关联查找 | `discovery` | Constrained multi-hop questions over people/entities |
| `strict` | 仅基于资料回答 | `strict_evidence=true` | Refusal or conservative answer when a fact is missing |

## Evaluation Modes

The product UI treats **mode** and **case subset** as separate controls:

| Mode | UI Label | What Runs | Main Signal |
|---|---|---|---|
| `retrieval_only` | 仅检索 | Query planning, retrieval, rerank, and trace only | `Hit@5`, `Hit@10`, expected document/chunk coverage, retrieval latency |
| `answer_lite` | 轻答案 | Retrieval + answer generation + deterministic/cached scoring | Answer/citation quality without a fresh judge call for every case |
| `full` | 完整 | Retrieval + answer generation + optional LLM judge | Release-style regression quality |

The smoke set is not a fourth product mode. It is a stable subset of representative cases used for quick checks. The backend still accepts `--mode quick` as a compatibility path, but the UI presents this as an **冒烟集** subset filter layered on top of the selected run mode.

## Running From CLI

Start backend first. For frequent retrieval checks, run retrieval-only:

```bash
cd backend
python scripts/eval_golden_set.py \
  --golden-set ../data/challenge_golden_set_v1.jsonl \
  --api-base http://127.0.0.1:8010/api \
  --mode retrieval_only \
  --concurrency 4 \
  --output ../data/challenge_golden_set_v1_results.jsonl
```

For release-style validation, run full mode with judge:

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
  --mode full \
  --judge \
  --slice recall
```

Useful slices:

```text
--slice balanced
--slice exact
--slice recall
--slice discovery
--slice strict
```

## Running From UI

Quality Center -> 基准测试集:

- view enabled and disabled cases
- run all enabled cases, smoke cases, or filter by flavor
- choose run mode: 仅检索, 轻答案, or 完整
- set per-case timeout for long-running cases
- set limited concurrency for faster runs
- see per-case progress while evaluation is running
- compare summary metrics against an accepted baseline
- edit case config and expected points
- enable, disable, or delete draft cases
- publish feedback drafts into the baseline set

The UI labels this workflow as **基准测试集**.

## Test Types

| Type | What It Scores |
|---|---|
| `rule` | Numeric expectations, required keywords, optional keywords, and citation recall |
| `llm_judge` | Complex expected points using an LLM judge, plus citation recall |
| `no_answer` | Correct refusal or conservative answer when the corpus lacks the target fact |

Rule cases are preferred for exact numeric policy checks. LLM judge cases are used for synthesis and discovery questions where wording can vary.

## Case Format

```json
{
  "id": "balanced_synth_002",
  "question": "星辰科技的安全事件报告和运维故障响应有什么关联和区别？",
  "eval_type": "llm_judge",
  "preferred_flavor": "balanced",
  "strict_evidence": false,
  "expected_points": [
    "安全事件要求4小时内报告",
    "安全事件P1响应时间30分钟",
    "运维故障P1响应时间5分钟、恢复时间30分钟"
  ],
  "expected_documents": ["03_信息安全策略", "06_运维故障处理手册"],
  "min_expected_citations": 2,
  "status": "active"
}
```

Important fields:

| Field | Purpose |
|---|---|
| `preferred_flavor` | Which retrieval strategy should be used for the case |
| `strict_evidence` | Whether the answer must refuse unsupported facts |
| `status` | `active` cases run by default; `disabled` cases stay in the set for reference |
| `numeric_expectations` | Numeric value + unit + tolerance for rule cases |
| `must_have` / `nice_to_have` | Required and optional answer terms for rule cases |
| `expected_points` | Checklist used by LLM judge cases |
| `expected_documents` | Source document substrings expected in citations |
| `expected_sections` | Optional source section hints |
| `min_expected_citations` | Minimum expected citation matches |
| `should_answer` | Whether the system should answer or refuse |

## Scoring

Each case records:

| Axis | Description |
|---|---|
| `answer_score` | Rule score or LLM judge score |
| `citation_score` | Fraction of expected source documents found in citations |
| `final_score` | Combined score used for verdict |
| `hit_at_5` / `hit_at_10` | Whether expected docs appeared in rerank results |
| `failure_category` | One or more categories explaining likely failure cause |
| `verdict` | `pass`, `warn`, `fail`, or `error` |

Verdict thresholds:

| Verdict | Meaning |
|---|---|
| `pass` | Score >= 0.8 |
| `warn` | Score >= 0.6 and < 0.8 |
| `fail` | Score < 0.6 |

## Output

| File | Content |
|---|---|
| `*_results.jsonl` | Per-case answer, citations, trace, rerank results, scores |
| `*_summary.json` | Aggregate score, pass rate, per-flavor and per-type breakdown |
| `accepted_baselines.json` | Latest accepted summary per mode/flavor for delta comparison |

## Current Demo Baseline

The current enabled baseline has been manually validated after the latest evaluation-loop, observability, chunk-quality, and background-job work. The latest full demo run completed successfully with one known warning case around judge/citation uncertainty; retrieval-only and smoke paths are fast enough for day-to-day checks.

Rerun the baseline after changes to:

- chunking rules
- search text or structured tag enrichment
- Milvus schema or embedding model
- retrieval budget, query expansion, multi-hop, rerank, context expansion, or prompt construction
- citation validation or evaluation scoring

## Failure Categories

Failure categories make a case actionable before reading the full JSONL output:

| Category | Meaning |
|---|---|
| `retrieval_miss` | Expected evidence did not appear in retrieved/reranked chunks |
| `rerank_drop` | Evidence was retrieved but dropped before final context |
| `context_loss` | Evidence was available but not carried into answer context |
| `citation_miss` | Expected document was present but not cited correctly |
| `answer_unsupported` | Answer made claims not supported by evidence |
| `answer_incomplete` | Answer missed expected points |
| `no_answer_wrong` | Strict/no-answer case was answered incorrectly |
| `timeout` | Case exceeded timeout |
| `judge_uncertain` | Judge output was warning-level or hard to parse |
| `pending_judge` | Full/quick-compatible run skipped judge for an LLM-judge case |

## Query Trace

Each streaming response includes structured trace events:

| Event | Content |
|---|---|
| `message_start` | Session info and query text |
| `retrieval_step` | Flavor, strict mode, entity match, search mode, expanded queries, per-query hit counts |
| `rerank` | Top reranked chunks and scores |
| `citations` | Final citation metadata |
| `trace` | Latency breakdown per stage |
| `message_end` | Final status and total latency |

## Query Statistics

The Quality Center stores online query stats and supports grouping by retrieval flavor and strict evidence mode.

Core metrics:

| Metric | Description |
|---|---|
| Total queries | Count across statuses |
| Success rate | Successful queries / total queries |
| Avg results | Average final result count |
| Rerank | Average rerank score |
| P95 latency | 95th percentile query latency |
| Expanded scope | Ratio of queries where entity fallback widened the search scope |

These online stats are operational metrics. They are not Hit@K or answer-quality metrics unless paired with the baseline test set.

## Rebuild Impact

Evaluation-only changes do not require reindexing. Rebuild Milvus only when the indexed artifacts change:

- embedding model or dimension
- chunking output
- table chunking
- `search_text`
- structured tag extraction rules used during ingestion
- parsed document artifacts
