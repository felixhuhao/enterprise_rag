# Prompt Reliability Implementation Plan

**Date:** 2026-06-11
**Source Audit:** `docs/prompt_reliability_audit.md`
**Related Audit:** `docs/keyword_matching_audit.md`

This plan separates prompt reliability work into two lanes:

1. **Implementation lane:** safe, local improvements that do not redesign query routing.
2. **Design lane:** query intent, routing, synthesis, broad-scope, and multi-hop behavior.

The implementation lane should continue now. The design lane needs a separate query-intent design before behavior changes.

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

If `test_hyde_search.py` does not exist yet, add it with prompt-format and normalization tests.

---

### 4. No-Answer And Refusal Behavior

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
- Use case metadata when available for no-answer entity checks:
  - `expected_entities`
  - `forbidden_entities`
  - entity names parsed from the question by the same eval case metadata path
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

**Related keyword findings:** broad signals, synthesis markers, multi-hop trigger, query expansion trigger.

**Goal:** Make current routing decisions inspectable without changing them.

**Changes:**

- Add a stable trace object for the current decision path:

```json
{
  "routing_decision": {
    "source": "current_rules",
    "selected_flavor": "balanced",
    "entity_mode": "single",
    "synthesis_budget_enabled": true,
    "synthesis_markers": ["比较"],
    "multi_hop_enabled": false,
    "multi_hop_triggers": [],
    "broad_signal_matched": "",
    "query_expansion_triggered": false,
    "query_expansion_reason": "",
    "defaulted": false,
    "reason_codes": ["synthesis_marker_match"]
  }
}
```

- Surface these fields in eval rows and query stats where useful.

**Acceptance criteria:**

- Existing route decisions are unchanged.
- Debug traces explain why the current system chose a path.
- Future query-intent work can compare new decisions against current decisions.
- Unit tests assert the exact `routing_decision` keys for representative cases:
  - synthesis marker match
  - broad entity signal match
  - multi-hop trigger match
  - no-rule/default balanced path

**Suggested verification:**

```bash
PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_query_planner.py -q
PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_query_stats.py -q
PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_eval_golden_set_config.py -q
```

If `test_query_planner.py` does not exist yet, add an equivalent focused test file for the routing trace helper.

---

## Requires Query-Intent Design

Do not implement these as standalone keyword patches:

### Query Intent Object

Needs a design for a single structured object consumed by planner, prompt builder, multi-hop, and tracing.

Likely fields:

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

Needs a design for deterministic signals plus optional structured LLM classification:

- temperature `0`
- bounded tokens
- strict JSON
- fallback to current deterministic behavior on errors
- shadow mode before behavior changes

### Decision Table

Needs a design mapping intent to:

- retrieval flavor
- retrieval budget
- prompt variant
- multi-hop/discovery behavior
- trace labels

### Routing Golden Set

Needs a dedicated set of paraphrase cases that intentionally avoid current trigger words:

- implicit comparisons
- mixed Chinese/English queries
- broad entity questions without `所有/哪些/各`
- discovery questions without current discovery keywords
- multi-hop responsibility questions with alternative phrasing

### Shadow Mode Success Metrics

Shadow mode needs objective gates before it can replace current routing.

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

1. Finish prompt/no-answer/groundedness fixes that preserve routing.
2. Validate HyDE prompt quality without changing model settings.
3. Add observability for current routing decisions.
4. Add routing-focused golden cases as baseline probes.
5. Write the query-intent design.
6. Implement query-intent in shadow mode.
7. Compare shadow decisions against current traces and golden cases using explicit success metrics.
8. Only then switch routing/synthesis behavior.

---

## Non-Goals

- Do not redesign retrieval strategy selection in this plan.
- Do not add new keyword lists as a long-term fix.
- Do not remove current routing behavior until a shadow-mode comparison exists.
- Do not expose experimental behavior as production-ready UI without a feature flag.
- Do not change the temperature or max-token settings committed in `9e43b2c` as part of this implementation lane.
