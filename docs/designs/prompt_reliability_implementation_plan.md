# Prompt Reliability Implementation Plan

**Date:** 2026-06-11
**Source Audit:** `../audits/prompt_reliability_audit.md`
**Related Audit:** `../audits/keyword_matching_audit.md`

This plan separates prompt reliability work into two lanes:

1. **Implementation lane:** safe, local improvements that do not redesign query routing.
2. **Design lane:** query intent, routing, synthesis, broad-scope, and multi-hop behavior.

## Status (updated 2026-06-14)

| Lane | Status |
|---|---|
| **Design lane** (query-intent routing) | **Complete** — all stages 2A–2D shipped. See `query_intent_routing_roadmap.md` and the "Requires Query-Intent Design" section below. |
| **Implementation lane — item 1** (Answer prompt contracts) | **Complete** — shared `ANSWER_CONTRACT` with contradiction handling and explicit no-answer wording, injected into all three prompt variants. |
| **Implementation lane — item 2** (Groundedness) | **Complete** — prompt simplified (nested rules removed, compact format); parser, tests, fallback, temp/max-token controls all shipped. |
| **Implementation lane — item 3** (HyDE) | **Complete** — output contract, 4 few-shot examples, `normalize_hyde_text` preamble stripping, and `test_hyde_search.py` all shipped. |
| **Implementation lane — item 4** (No-answer/refusal) | **Complete** — `REFUSAL_SIGNALS` expanded; 5-company hardcode removed; `forbidden_entities` metadata drives entity checks with clause-local matching; unknown entities no longer silently exempt (`unscored_reason`). |
| **Implementation lane — item 5** (Eval coverage) | **Mostly done** — contradiction, near-miss, threshold-boundary, exception-priority, and paraphrase cases added. Optional cleanup remains: no dedicated citation-placement-on-numerics probe; `slices` field still inconsistent (8/31). |
| **Implementation lane — item 6** (Observability) | **Superseded** — the design lane built a richer tiered trace (`intent`/`policy`/`infra`/`routing_decision`/`inline_shadow`) than this item's flat schema. |

No blocking work remains. Item 5 has minor optional cleanup gaps; item 6 was superseded by the design lane.

---

## Boundary

Do not use this plan to patch query routing with more keyword lists. The following are coupled and should be redesigned together:

- synthesis detection
- comparison routing
- broad/entity-scope detection
- discovery and multi-hop triggering
- retrieval budget selection
- prompt variant selection when it depends on query intent

Safe implementation work may improve prompts, output contracts, scoring, parser reliability, evaluation coverage, and observability as long as it preserves the current routing decisions.

Also keep the LLM temperature and max-token settings introduced in commit `9e43b2c` fixed while doing prompt work. Prompt changes should not be mixed with model-parameter retuning, otherwise regressions become hard to attribute.

---

## Safe Fixes Now

### 1. Answer Prompt Output Contracts

**Status:** Complete. A shared `ANSWER_CONTRACT` (`build_prompt.py:16-25`) is injected into all three prompt variants via `{answer_contract}`. It covers: direct-answer-first, citation on every factual/numeric claim, contradiction handling (state conflict, cite both sides, prefer newer only when evidence says so), and explicit no-answer wording ("资料中未提供该信息，无法从资料确认" + anti-inference + anti-false-absence). Multi-entity and broad variants add their own organization rules on top. Tests assert all three contract surfaces.

**Audit findings:** Prompt reliability findings 1, 2, 3, 6.

**Goal:** Make generated answers more predictable without changing which retrieval path is selected.

**Changes:**

- Define a shared answer contract for normal, multi-entity, and broad answer prompts.
- Require compact Markdown with predictable sections only when useful:
  - direct answer first
  - bullets or table for comparisons
  - no unsupported facts
  - every factual/numeric claim carries citations
- Add explicit contradiction handling:
  - state the conflict
  - cite both sides
  - prefer newer/effective policy only when evidence says so
- Add explicit no-answer wording for missing evidence:
  - say the corpus does not provide the requested fact
  - do not infer from nearby facts
  - do not cite unrelated evidence as proof of absence

**Acceptance criteria:**

- Prompt text clearly distinguishes answer, no-answer, and contradictory-evidence behavior.
- Existing answer generation tests pass.
- Golden-set no-answer and strict-evidence cases do not regress.

**Suggested verification:**

```bash
PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_build_prompt.py -q
PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_eval_golden_set_config.py -q
```

Run golden-set `retrieval_only` first, then `full --judge` for release-style validation.

---

### 2. Groundedness Prompt Simplification And Reliability

**Status:** Complete. The prompt was simplified from ~34 lines of nested rule blocks to ~22 compact lines (`groundedness.py:18-41`). The `no_answer 特殊判定规则` and `factual 关键规则` nested blocks were removed; their logic is enforced in code by `_validate_claims`. The reliability half was already shipped: shared `llm_json.py` parser, comprehensive parser tests, structured `unavailable` fallback, and `GROUNDEDNESS_TEMPERATURE`/`GROUNDEDNESS_MAX_TOKENS` in settings. Test asserts `len(GROUNDEDNESS_PROMPT) < 900` and absence of old nested-rule markers.

**Audit findings:** Prompt reliability findings 5 and 13.

**Goal:** Make groundedness checks easier for the model to follow, then harden recovery when the model still emits imperfect JSON.

**Changes:**

- Simplify the groundedness prompt itself. Finding 5 identifies prompt complexity as the root issue, not only parser fragility.
- Remove nested rule sets where possible:
  - keep the model task to claim classification and evidence matching
  - move deterministic citation cleanup and no-answer citation normalization into code
  - avoid long special-case prose inside the prompt when a post-processing rule can enforce it
- Split the prompt into a short role/task block, a compact schema block, and minimal rules.
- Keep no-answer handling explicit, but avoid nested sub-rules that compete with the JSON contract.
- Keep groundedness temperature and max-token controls explicit in settings.
- Tighten the JSON output contract and keep it short.
- Add parser tests for:
  - strict JSON
  - fenced JSON
  - extra prose around JSON
  - empty/malformed output
  - no-answer claims with and without citation IDs
- Prefer structured repair/fallback behavior over silent parse failure.

**Acceptance criteria:**

- Groundedness prompt is materially shorter and easier to scan than the current prompt.
- The simplified prompt still covers factual and no-answer claim types.
- Groundedness parser behavior is covered by unit tests.
- Malformed judge output produces a clear warning state, not an ambiguous success.
- Existing groundedness no-answer behavior stays intact.

**Suggested verification:**

```bash
PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_groundedness.py -q
```

---

### 3. HyDE Prompt Quality Validation

**Status:** Complete. The prompt (`hyde_search.py:39-77`) now has: an explicit output contract (2-3 sentences, 80-160字, no preamble, preserve entities/dates/numbers/policy names, conservative for exact values), four few-shot examples (exact lookup, vague recall, cross-entity comparison, conservative no-answer), and `normalize_hyde_text` (`hyde_search.py:163-174`) which strips markdown fences and common preambles via `_HYDE_PREAMBLE_RE` before embedding. `test_hyde_search.py` covers prompt contract presence, preamble stripping, nested preamble, fence stripping, and plain content preservation. Temperature/max-token settings (`HYDE_TEMPERATURE=0.3`, `HYDE_MAX_TOKENS=256`) remain unchanged from `9e43b2c`.

**Audit finding:** Prompt reliability finding 4.

**Goal:** Ensure HyDE output improves retrieval instead of polluting embeddings with verbose or generic hypothetical text.

**Changes:**

- Keep the temperature and max-token settings from `9e43b2c`; do not retune them in this work.
- Add a stricter HyDE output contract:
  - one short paragraph or 2-3 compact sentences
  - no preamble such as `以下是假设性回答`
  - preserve user-provided entities, dates, numbers, and policy names
  - avoid unsupported invented values when the user asks for an exact value
- Add few-shot examples for:
  - exact policy lookup
  - vague recall query
  - cross-entity comparison
  - no-answer/strict-evidence style query where HyDE should stay conservative
- Normalize/strip common preambles before embedding as a defensive fallback.
- Validate HyDE retrieval quality with retrieval-only golden runs and HyDE-sensitive cases.

**Acceptance criteria:**

- HyDE output is bounded, preamble-free, and preserves key query terms in unit tests.
- Retrieval-only Hit@5/Hit@10 does not regress on the golden set.
- HyDE-sensitive cases show equal or better expected-document coverage compared with the current prompt.
- Any prompt change that reduces retrieval coverage is reverted or kept behind a flag.

**Suggested verification:**

```bash
PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_hyde_search.py -q
docker compose exec -T backend sh -lc 'PYTHONPATH=/app python scripts/eval_golden_set.py --golden-set /app/data/challenge_golden_set_v1.jsonl --api-base http://127.0.0.1:8010/api --mode retrieval_only --concurrency 2 --delay 0 --case-timeout 240 --output /app/data/challenge_golden_set_v1_hyde_check_results.jsonl'
```

---

### 4. No-Answer And Refusal Behavior

**Status:** Complete. `REFUSAL_SIGNALS` (`numeric.py:5-16`) expanded with `上下文未提供`, `资料中未提及`, `无法从资料确认`. The hardcoded five-company list is removed. `score_no_answer` (`scorers.py:208-243`) now reads `forbidden_entities` from case metadata and uses clause-local matching (`_entity_financial_hits` + `_financial_check_clauses`) so a financial number in a different sentence, semicolon-separated clause, or newline does not produce a false hit. Same-sentence comma cases remain conservative: if a forbidden entity appears before a financial number in the same clause/sentence, the scorer still treats it as unsafe. When no `forbidden_entities` metadata exists, generic financial hallucination is still checked and an explicit `unscored_reason` is returned. Tests cover refusal variants, forbidden-entity detection, clause-local isolation, missing-metadata pass, and missing-metadata hallucination fail.

**Audit findings:** Prompt reliability findings 1 and 5; keyword matching audit findings 8 and 9; current evaluator false-negative fixes.

**Goal:** Make refusal behavior consistent across prompts, groundedness, and golden-set scoring.

**Changes:**

- Centralize accepted refusal/no-answer phrases used by evaluators. This directly addresses keyword matching audit finding 8 (`REFUSAL_SIGNALS` in `backend/scripts/eval_golden/numeric.py`).
- Add tests for common Chinese refusal variants:
  - `未找到...相关信息`
  - `上下文未提供...`
  - `资料中未提及...`
  - `无法从资料确认...`
- Remove or replace the hardcoded five-company list in `score_no_answer` for out-of-scope entity checks. This directly addresses keyword matching audit finding 9 (`backend/scripts/eval_golden/scorers.py`).
- Use `forbidden_entities` case metadata when available for no-answer entity checks.
- If no entity metadata exists, do not silently skip hallucination checks for unknown entities; return an explicit `unscored_reason` or use generic forbidden-pattern checks.
- Ensure no-answer scoring does not penalize correct refusals that use natural wording.
- Ensure answer prompts do not instruct the model to answer from adjacent but unsupported facts.

**Acceptance criteria:**

- Correct no-answer responses score as pass.
- Hallucinated values in no-answer cases still fail.
- Unknown entities are not silently exempt from no-answer hallucination checks.
- Out-of-scope entity scoring has tests for an entity outside the old hardcoded list.
- Strict-evidence golden cases remain stable.

**Suggested verification:**

```bash
PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_eval_golden_set_config.py -q
```

---

### 5. Evaluation Coverage

**Status:** Mostly done. The 31-case `challenge_golden_set_v1.jsonl` covers: contradictory evidence (2 `矛盾检测`), near-miss/insufficient evidence (3 `证据不足`/`近邻缺失`), comparison answers (8 `comparison`/`多实体对比`), discovery/multi-hop (4 cases), threshold-boundary, exception-priority, and paraphrase recall. Minor gaps remain: no dedicated citation-placement-on-numerics probe; `slices` field is populated on only 8/31 cases. A dedicated routing golden set (`routing_golden_set_v1.jsonl`, 40 cases) was added separately by the design lane (2C-1).

**Audit findings:** Cross-cutting.

**Goal:** Add regression coverage before changing deeper behavior.

**Changes:**

- Add golden cases for:
  - contradictory policy evidence
  - missing facts that have nearby related evidence
  - citation placement on numeric facts
  - no-answer phrasing variants
  - prompt-format-sensitive comparison answers
- Add routing-focused cases as baseline probes, but do not require routing redesign yet.
  - These cases can document current behavior and expected future improvements.

**Acceptance criteria:**

- Cases are labeled by slice/tag so prompt regressions and routing regressions can be separated.
- Retrieval-only still passes before answer-quality changes are evaluated.
- Full-mode baseline changes are explained case by case.

**Suggested verification:**

```bash
docker compose exec -T backend sh -lc 'PYTHONPATH=/app python scripts/eval_golden_set.py --golden-set /app/data/challenge_golden_set_v1.jsonl --api-base http://127.0.0.1:8010/api --mode retrieval_only --concurrency 2 --delay 0 --case-timeout 240 --output /app/data/challenge_golden_set_v1_retrieval_only_results.jsonl'
docker compose exec -T backend sh -lc 'PYTHONPATH=/app python scripts/eval_golden_set.py --golden-set /app/data/challenge_golden_set_v1.jsonl --api-base http://127.0.0.1:8010/api --mode full --judge --concurrency 2 --delay 0 --case-timeout 300 --output /app/data/challenge_golden_set_v1_full_judge_results.jsonl'
```

---

### 6. Observability For Current Decisions

**Status:** Superseded by the design lane. The plan's flat `routing_decision` schema was replaced by a richer tiered trace (`routing_trace` with `intent`/`policy`/`infra`/`routing_decision`/`inline_shadow` sections) built incrementally across 2A–2D. It is persisted into `query_run_stats` via `resolved_settings.routing_trace` and covered by `test_control_routing.py` / `test_query_stats.py`. What remains, if ever needed, is optional trace-detail enrichment: the old plan called for exact trigger text (`synthesis_markers`, `multi_hop_triggers`, `broad_signal_matched`, `query_expansion_reason`, `defaulted`), while `infer_signals` records only coarse reason codes (e.g. `synthesis:marker`). Eval rows (`runner.py`) do not surface `routing_trace` at the top level.

The old flat-schema proposal below is historical only and should not be implemented:

- `routing_decision.source`
- `routing_decision.selected_flavor`
- exact marker strings such as `synthesis_markers` / `multi_hop_triggers`
- `query_expansion_triggered` / `query_expansion_reason`
- `defaulted`

Use the shipped `routing_trace` shape instead.

---

## Requires Query-Intent Design — COMPLETE

All items below were designed and shipped via the staged roadmap in `query_intent_routing_roadmap.md` (stages 2A–2D). Each has its own design + plan doc in `docs/designs/`. See the roadmap for the full status trail.

Do not implement these as standalone keyword patches:

### Query Intent Object

Delivered by 2A–2D as a structured intent/routing trace consumed by planner, prompt selection, multi-hop, and observability.

Core delivered fields include:

- `entity_scope`
- `needs_synthesis`
- `comparison_type`
- `needs_discovery`
- `needs_multi_hop`
- `answer_shape`
- `confidence`
- `reasons`
- `fallback_used`

### Hybrid Classifier

Delivered by 2B/2C as deterministic signals plus optional structured LLM classification:

- temperature `0`
- bounded tokens
- strict JSON
- fallback to current deterministic behavior on errors
- shadow mode before behavior changes

### Decision Table

Delivered by Design 1 + 2A–2D as the mapping from intent to:

- retrieval flavor
- retrieval budget
- prompt variant
- multi-hop/discovery behavior
- trace labels

### Routing Golden Set

Delivered by 2C-1 as `routing_golden_set_v1.jsonl`, a dedicated set of paraphrase cases that intentionally avoid current trigger words:

- implicit comparisons
- mixed Chinese/English queries
- broad entity questions without `所有/哪些/各`
- discovery questions without current discovery keywords
- multi-hop responsibility questions with alternative phrasing

### Shadow Mode Success Metrics

Delivered across 2C-1 through 2C-3 as objective gates before replacing current routing.

Minimum comparison set:

- current golden set
- routing-focused paraphrase set
- at least one manually labeled route expectation per routing case

Initial success criteria:

- Retrieval-only Hit@5 and Hit@10 do not regress on the current golden set.
- Full-mode pass rate does not regress beyond the accepted baseline tolerance.
- On manually labeled high-confidence routing cases, new intent routing matches the expected route at least 90% of the time.
- On ambiguous cases, the classifier must either select the expected route or return low confidence and default to the current safe route.
- Every mismatch has a recorded reason and is reviewed before rollout.
- Improvement is measured as expected-route accuracy versus the current keyword-routing baseline, not just subjective readability of traces.

---

## Recommended Order

1. ~~Finish prompt/no-answer/groundedness fixes that preserve routing.~~ — **Done** (items 1, 2, 4).
2. ~~Validate HyDE prompt quality without changing model settings.~~ — **Done** (item 3).
3. ~~Add observability for current routing decisions.~~ — **Done** (superseded by design lane; item 6).
4. ~~Add routing-focused golden cases as baseline probes.~~ — **Done** (2C-1 `routing_golden_set_v1.jsonl`).
5. ~~Write the query-intent design.~~ — **Done** (2A–2D design docs).
6. ~~Implement query-intent in shadow mode.~~ — **Done** (2A shadow, 2B offline replay, 2C-2 inline shadow).
7. ~~Compare shadow decisions against current traces and golden cases using explicit success metrics.~~ — **Done** (2C-1 scorer, 2C-3 paired eval + comparator).
8. ~~Only then switch routing/synthesis behavior.~~ — **Done** (2C-3 activation, 2D discovery retirement).

---

## Non-Goals

- Do not redesign retrieval strategy selection in this plan.
- Do not add new keyword lists as a long-term fix.
- Do not remove current routing behavior until a shadow-mode comparison exists.
- Do not expose experimental behavior as production-ready UI without a feature flag.
- Do not change the temperature or max-token settings committed in `9e43b2c` as part of this implementation lane.
