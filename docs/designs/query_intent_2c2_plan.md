# Query-Intent Routing 2C-2 (Inline Shadow) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the intent classifier inline on every live query behind two `runtime_settings` kill switches, recording what it *would* route while the emitted `query_plan` stays byte-for-byte 2A, so the 2C-3 activation flip has production-shadow evidence.

**Architecture:** A planner-local seam computes a deterministic routing *bundle* `(intent, decision, budget)`; when `intent.inline_enabled` is on, an inline LLM classifier produces a merged proposal bundle, a trust gate selects between them, and an `inline_shadow` trace block records the raw pre-gate proposal vs the deterministic route. The emitted bundle is the gated one only when `intent.active_mode` is on (off in 2C-2), so the plan never changes. An offline script aggregates the shadow rows from `query_run_stats` into the go/no-go gate.

**Tech Stack:** Python 3, langchain-openai (`ChatOpenAI`), pydantic-settings, SQLite (`query_run_stats`), pytest. Spec: `docs/designs/query_intent_2c2_design.md`.

---

## File structure

| File | Responsibility | Change |
| --- | --- | --- |
| `backend/app/config.py` | env tuning params | **Modify** — add `INTENT_CLASSIFIER_INLINE_TIMEOUT: int = 6` |
| `backend/app/rag/query/control/llm_classifier.py` | LLM intent classifier | **Modify** — factor `_invoke_classifier` raw seam; add `ClassifyResult`, `_is_timeout`, `classify_intent_inline`; refactor `classify_intent_llm` to delegate |
| `backend/app/rag/query/control/routing.py` | derived routing + shadow | **Modify** — add `activatable`, `trust_gate_bundle`, `build_inline_shadow`, `inactive_inline_shadow`; rework `build_routing_trace` to take an `inline_shadow` dict (replaces `shadow_routing`) |
| `backend/app/core/runtime_settings.py` | runtime flags | **Modify** — register `intent.inline_enabled` / `intent.active_mode` defaults |
| `backend/app/rag/query/planner.py` | request-path planner | **Modify** — `_route_bundle_for` helper, `_intent_flag`, `_inline_intent` seam, rewire `query_plan_node` to bundles + flags |
| `backend/scripts/report_inline_shadow.py` | offline shadow gate report | **Create** — `aggregate_inline_shadow` + DB-reading `main` |
| `backend/tests/unit/test_llm_classifier.py` | classifier tests | **Modify** — inline envelope + reason taxonomy |
| `backend/tests/unit/test_control_routing.py` | routing tests | **Modify** — gate bundle + shadow + trace |
| `backend/tests/unit/test_query_planner.py` | planner tests | **Modify** — preservation, active wiring, fallback, kill switch |
| `backend/tests/unit/test_inline_shadow_report.py` | report tests | **Create** — aggregation unit test |

**Test runner:** from repo root, `source .venv/bin/activate` once, then run pytest from `backend/`:
```bash
cd /home/hao/workspace/enterprise_rag && source .venv/bin/activate && cd backend
```
All commands below assume that activated venv and `backend/` as cwd.

---

### Task 1: Inline classifier seam + reason taxonomy

**Files:**
- Modify: `backend/app/config.py:44`
- Modify: `backend/app/rag/query/control/llm_classifier.py:1-62`
- Test: `backend/tests/unit/test_llm_classifier.py`

- [ ] **Step 1: Add the inline timeout setting**

In `backend/app/config.py`, immediately after line 44 (`INTENT_CLASSIFIER_TIMEOUT: int = 30`), add:

```python
    INTENT_CLASSIFIER_INLINE_TIMEOUT: int = 6
```

- [ ] **Step 2: Write the failing tests for the inline envelope**

Append to `backend/tests/unit/test_llm_classifier.py`:

```python
from app.rag.query.control import llm_classifier
from app.rag.query.control.inferred import InferredSignals


def _det(confidence="medium"):
    return InferredSignals("single", False, False, False, confidence=confidence)


def test_classify_intent_inline_success(monkeypatch):
    monkeypatch.setattr(
        llm_classifier,
        "_invoke_classifier",
        lambda q, d, t: '{"needs_synthesis":true,"needs_discovery":false,'
        '"confidence":"high","reasons":["x"]}',
    )
    result = llm_classifier.classify_intent_inline("q", _det())
    assert result.fallback_reason == "none"
    assert result.markers is not None
    assert result.markers.needs_synthesis is True
    assert result.latency_ms >= 0


def test_classify_intent_inline_parse_fail(monkeypatch):
    monkeypatch.setattr(llm_classifier, "_invoke_classifier", lambda q, d, t: "not json")
    result = llm_classifier.classify_intent_inline("q", _det())
    assert result.fallback_reason == "parse_fail"
    assert result.markers is None


def test_classify_intent_inline_timeout(monkeypatch):
    class APITimeoutError(Exception):
        pass

    def boom(q, d, t):
        raise APITimeoutError("slow")

    monkeypatch.setattr(llm_classifier, "_invoke_classifier", boom)
    result = llm_classifier.classify_intent_inline("q", _det())
    assert result.fallback_reason == "timeout"
    assert result.markers is None


def test_classify_intent_inline_error(monkeypatch):
    def boom(q, d, t):
        raise ValueError("boom")

    monkeypatch.setattr(llm_classifier, "_invoke_classifier", boom)
    result = llm_classifier.classify_intent_inline("q", _det())
    assert result.fallback_reason == "error"
    assert result.markers is None


def test_is_timeout_recognizes_provider_types():
    class APITimeoutError(Exception):
        pass

    class TimeoutException(Exception):
        pass

    assert llm_classifier._is_timeout(APITimeoutError()) is True
    assert llm_classifier._is_timeout(TimeoutException()) is True
    assert llm_classifier._is_timeout(TimeoutError()) is True
    assert llm_classifier._is_timeout(ValueError()) is False


def test_is_timeout_recognizes_wrapped_provider_timeout():
    class APITimeoutError(Exception):
        pass

    wrapped = RuntimeError("request failed")
    wrapped.__cause__ = APITimeoutError("slow")

    assert llm_classifier._is_timeout(wrapped) is True


def test_classify_intent_llm_delegates_and_swallows(monkeypatch):
    monkeypatch.setattr(
        llm_classifier,
        "_invoke_classifier",
        lambda q, d, t: '{"needs_synthesis":false,"needs_discovery":true,'
        '"confidence":"high","reasons":[]}',
    )
    markers = llm_classifier.classify_intent_llm("q", _det())
    assert markers is not None and markers.needs_discovery is True

    def boom(q, d, t):
        raise ValueError("x")

    monkeypatch.setattr(llm_classifier, "_invoke_classifier", boom)
    assert llm_classifier.classify_intent_llm("q", _det()) is None
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_llm_classifier.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute '_invoke_classifier'` / `classify_intent_inline`.

- [ ] **Step 4: Implement the seam, envelope, and delegation**

In `backend/app/rag/query/control/llm_classifier.py`, change the imports at the top (currently `from dataclasses import dataclass, field, replace`) to also import `time`, and add the envelope + helpers. Replace the existing `classify_intent_llm` function (lines ~38-62) with the delegating version and the new functions:

```python
import logging
import time
from dataclasses import dataclass, field, replace
```

Add after the `LlmMarkers` dataclass:

```python
@dataclass(frozen=True)
class ClassifyResult:
    markers: "LlmMarkers | None"
    fallback_reason: str  # "none" | "timeout" | "error" | "parse_fail"
    latency_ms: int


_TIMEOUT_EXC_NAMES = {
    "APITimeoutError",    # openai
    "Timeout",            # openai legacy / requests
    "TimeoutException",   # httpx
    "ReadTimeout",        # httpx / requests
    "WriteTimeout",       # httpx
    "TimeoutError",       # builtins / asyncio / concurrent.futures
}


def _is_timeout(exc: BaseException) -> bool:
    """Recognize provider/client timeout types, including wrapped causes."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, TimeoutError):
            return True
        if type(current).__name__ in _TIMEOUT_EXC_NAMES:
            return True
        current = current.__cause__ or current.__context__
    return False
```

Replace `classify_intent_llm` with the shared raw seam + both entry points:

```python
def _invoke_classifier(query: str, deterministic: InferredSignals, timeout: int) -> str:
    """Build the client, invoke, return raw content. Does NOT catch — callers decide."""
    llm = ChatOpenAI(
        model=_classifier_model(),
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
        timeout=timeout,
        max_retries=1,
        temperature=settings.INTENT_CLASSIFIER_TEMPERATURE,
        max_tokens=settings.INTENT_CLASSIFIER_MAX_TOKENS,
    )
    response = llm.invoke(
        [
            SystemMessage(content=INTENT_CLASSIFIER_SYSTEM),
            HumanMessage(content=_classifier_user_prompt(query, deterministic)),
        ],
        timeout=timeout,
    )
    raw = response.content if hasattr(response, "content") else str(response)
    return str(raw or "")


def classify_intent_llm(query: str, deterministic: InferredSignals) -> "LlmMarkers | None":
    """Offline entry point: markers or None on any call/parse/contract failure."""
    try:
        raw = _invoke_classifier(query, deterministic, settings.INTENT_CLASSIFIER_TIMEOUT)
        return _calibrate_confidence(parse_llm_markers(raw), deterministic)
    except Exception:
        logger.warning("Intent classifier LLM call failed", exc_info=True)
        return None


def classify_intent_inline(query: str, deterministic: InferredSignals) -> ClassifyResult:
    """Inline entry point: time the call and classify the failure reason."""
    start = time.monotonic()
    try:
        raw = _invoke_classifier(query, deterministic, settings.INTENT_CLASSIFIER_INLINE_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 — taxonomy below, never re-raised into request path
        reason = "timeout" if _is_timeout(exc) else "error"
        latency_ms = int((time.monotonic() - start) * 1000)
        logger.warning("Inline intent classifier fallback=%s latency_ms=%d", reason, latency_ms)
        return ClassifyResult(markers=None, fallback_reason=reason, latency_ms=latency_ms)
    latency_ms = int((time.monotonic() - start) * 1000)
    markers = parse_llm_markers(raw)
    if markers is None:
        logger.warning("Inline intent classifier fallback=parse_fail latency_ms=%d", latency_ms)
        return ClassifyResult(markers=None, fallback_reason="parse_fail", latency_ms=latency_ms)
    return ClassifyResult(
        markers=_calibrate_confidence(markers, deterministic),
        fallback_reason="none",
        latency_ms=latency_ms,
    )
```

Note: `_calibrate_confidence`, `parse_llm_markers`, `_classifier_model`, `_classifier_user_prompt`, `INTENT_CLASSIFIER_SYSTEM` already exist and are unchanged.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_llm_classifier.py -q`
Expected: PASS (all existing + 7 new).

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py backend/app/rag/query/control/llm_classifier.py backend/tests/unit/test_llm_classifier.py
git commit -m "feat(2C-2): inline classifier seam with fallback-reason taxonomy

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Bundle trust gate + inline shadow + trace rework

**Files:**
- Modify: `backend/app/rag/query/control/routing.py:90-160`
- Test: `backend/tests/unit/test_control_routing.py`

- [ ] **Step 1: Write the failing tests**

In `backend/tests/unit/test_control_routing.py`, add these imports to the existing `from app.rag.query.control.routing import (...)` block: `activatable`, `trust_gate_bundle`, `build_inline_shadow`, `inactive_inline_shadow`, `decision_execution_dict`. Then add a small fake result and the tests:

```python
from dataclasses import dataclass
from app.rag.query.control.inferred import InferredSignals


@dataclass
class _FakeResult:
    markers: object
    fallback_reason: str
    latency_ms: int


def _intent(confidence="high", fallback_used=False, needs_synthesis=False):
    return InferredSignals(
        "single", needs_synthesis, False, False,
        confidence=confidence, fallback_used=fallback_used, source="llm_escalated",
    )


def test_activatable_requires_high_and_not_fallback():
    assert activatable(_intent("high")) is True
    assert activatable(_intent("medium")) is False
    assert activatable(_intent("high", fallback_used=True)) is False


def test_trust_gate_uses_shared_activatable_predicate_for_fallback():
    inferred = _routing_decision(use_query_expansion=True)
    design1 = _routing_decision(use_query_expansion=False)
    assert trust_gate(_intent("high", fallback_used=True), inferred, design1) is design1


def test_trust_gate_bundle_selects_merged_when_activatable():
    det = (_intent("high"), "DET_DEC", "DET_BUD")
    merged = (_intent("high", needs_synthesis=True), "MERGED_DEC", "MERGED_BUD")
    assert trust_gate_bundle(merged, det) is merged


def test_trust_gate_bundle_falls_back_when_not_activatable():
    det = (_intent("high"), "DET_DEC", "DET_BUD")
    merged_lo = (_intent("medium", needs_synthesis=True), "MERGED_DEC", "MERGED_BUD")
    merged_fb = (_intent("high", fallback_used=True), "MERGED_DEC", "MERGED_BUD")
    assert trust_gate_bundle(merged_lo, det) is det
    assert trust_gate_bundle(merged_fb, det) is det


def test_build_inline_shadow_diverged_high_is_activatable():
    det_int = _intent("high")
    det_dec = _routing_decision(use_query_expansion=False)
    merged_int = _intent("high", needs_synthesis=True)
    merged_dec = _routing_decision(use_query_expansion=True)
    shadow = build_inline_shadow(
        _FakeResult(markers=object(), fallback_reason="none", latency_ms=42),
        (merged_int, merged_dec, "B"),
        (det_int, det_dec, "B"),
    )
    assert shadow["ran"] is True
    assert shadow["fallback_used"] is False
    assert shadow["proposal_diverged"] is True
    assert shadow["activatable_diverged"] is True
    assert shadow["latency_ms"] == 42
    assert shadow["merged_markers"]["needs_synthesis"] is True


def test_build_inline_shadow_diverged_low_not_activatable():
    det_int = _intent("high")
    merged_int = _intent("medium", needs_synthesis=True)
    shadow = build_inline_shadow(
        _FakeResult(markers=object(), fallback_reason="none", latency_ms=7),
        (merged_int, _routing_decision(use_query_expansion=True), "B"),
        (det_int, _routing_decision(use_query_expansion=False), "B"),
    )
    assert shadow["proposal_diverged"] is True
    assert shadow["activatable_diverged"] is False


def test_build_inline_shadow_converged():
    det_int = _intent("high")
    dec = _routing_decision(use_query_expansion=False)
    shadow = build_inline_shadow(
        _FakeResult(markers=object(), fallback_reason="none", latency_ms=1),
        (_intent("high"), dec, "B"),
        (det_int, dec, "B"),
    )
    assert shadow["proposal_diverged"] is False
    assert shadow["activatable_diverged"] is False


def test_inactive_inline_shadow():
    shadow = inactive_inline_shadow()
    assert shadow == {"ran": False, "fallback_reason": "none"}
```

Add this decision factory near the top of the test file (after imports) if one does not already exist:

```python
def _routing_decision(**overrides):
    from app.rag.query.control.routing import RoutingDecision

    base = dict(
        use_hyde=True, use_query_expansion=False, use_multi_hop=False,
        use_entity_fallback=True, budget_reason="balanced", prompt_variant="default",
        answer_shape="prose", steps=[], reasons=[], vetoes=[],
    )
    base.update(overrides)
    return RoutingDecision(**base)
```

Now **replace** the existing trace tests that reference `shadow_routing`. Change `test_trace_has_intent_provenance_and_shadow_routing` and the two `_shadow_routing`/`would_be` divergence tests (the block around the current lines 78-138) to assert the new shape:

```python
def test_build_routing_trace_keys_include_inline_shadow():
    sig = _intent("high")
    d = _routing_decision()
    trace = build_routing_trace(sig, "precise", CFG, d, inactive_inline_shadow())
    assert set(trace) == {"intent", "policy", "infra", "routing_decision", "inline_shadow"}
    assert trace["inline_shadow"]["ran"] is False


def test_build_routing_trace_embeds_inline_shadow():
    sig = _intent("high")
    d = _routing_decision()
    shadow = {"ran": True, "fallback_reason": "none", "proposal_diverged": True}
    trace = build_routing_trace(sig, "balanced", CFG, d, shadow)
    assert trace["inline_shadow"] is shadow
```

Update the existing `trust_gate` tests to reflect the shared activation predicate: high/non-fallback uses the inferred decision, below-high uses Design 1, and high-with-`fallback_used=True` uses Design 1. This keeps the 2C-1 scorer, which still calls `trust_gate`, consistent with live `trust_gate_bundle`. Use the file's existing `CFG` constant; if it does not exist, add `CFG = QueryConfig()` near the top.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_control_routing.py -q`
Expected: FAIL — `ImportError: cannot import name 'activatable'` and key-set mismatch on the trace tests.

- [ ] **Step 3: Implement gate, shadow, and trace rework**

In `backend/app/rag/query/control/routing.py`, replace the existing `trust_gate` with `activatable` + an updated `trust_gate`, then add the bundle gate and inline-shadow helpers:

```python
def activatable(intent: InferredSignals) -> bool:
    """A route may drive only at high confidence and never on a fallback."""
    return intent.confidence == "high" and not intent.fallback_used


def trust_gate(
    intent: InferredSignals,
    inferred_decision: RoutingDecision,
    design1_decision: RoutingDecision,
) -> RoutingDecision:
    """Trust the inferred route only when the shared activation predicate passes."""
    return inferred_decision if activatable(intent) else design1_decision


def trust_gate_bundle(merged_bundle: tuple, det_bundle: tuple) -> tuple:
    """Select the whole (intent, decision, budget) bundle.

    Returns the merged bundle iff the merged intent is activatable, else the
    deterministic bundle — so intent, decision, and budget never disagree.
    """
    merged_intent = merged_bundle[0]
    return merged_bundle if activatable(merged_intent) else det_bundle


def build_inline_shadow(result, merged_bundle: tuple, det_bundle: tuple) -> dict:
    """Record the raw pre-gate LLM proposal vs the deterministic route.

    `result` is a ClassifyResult (duck-typed: .markers, .fallback_reason, .latency_ms).
    Excised wholesale in 2D.
    """
    merged_intent, merged_decision, _merged_budget = merged_bundle
    _det_intent, det_decision, _det_budget = det_bundle
    proposal_execution = decision_execution_dict(merged_decision)
    proposal_diverged = proposal_execution != decision_execution_dict(det_decision)
    return {
        "ran": True,
        "fallback_used": result.markers is None,
        "fallback_reason": result.fallback_reason,
        "latency_ms": result.latency_ms,
        "confidence": merged_intent.confidence,
        "merged_markers": {
            "needs_synthesis": merged_intent.needs_synthesis,
            "needs_discovery": merged_intent.needs_discovery,
            "needs_multi_hop": merged_intent.needs_multi_hop,
        },
        "merged_reasons": list(merged_intent.reasons),
        "merged_source": merged_intent.source,
        "proposal_execution": proposal_execution,
        "proposal_diverged": proposal_diverged,
        "activatable_diverged": proposal_diverged and activatable(merged_intent),
    }


def inactive_inline_shadow() -> dict:
    """Trace block when the inline classifier did not run."""
    return {"ran": False, "fallback_reason": "none"}
```

Then **rework `build_routing_trace`**: change its last parameter from `would_be_decision: RoutingDecision` to `inline_shadow: dict`, and replace the final dict entry. Replace lines 103-160 (the `build_routing_trace` body and the `_shadow_routing` helper) so the function ends with:

```python
def build_routing_trace(
    inferred: InferredSignals,
    breadth: RetrievalBreadth,
    cfg: QueryConfig,
    decision: RoutingDecision,
    inline_shadow: dict,
) -> dict:
    """Trace the three tiers, emitted decision, and inline-shadow record."""
    return {
        "intent": {
            "entity_scope": inferred.entity_scope,
            "needs_synthesis": inferred.needs_synthesis,
            "needs_discovery": inferred.needs_discovery,
            "needs_multi_hop": inferred.needs_multi_hop,
            "confidence": inferred.confidence,
            "source": inferred.source,
            "fallback_used": inferred.fallback_used,
            "reasons": inferred.reasons,
        },
        "policy": {
            "retrieval_breadth": breadth,
            "strict_evidence": bool(cfg.strict_evidence),
            "vetoes": decision.vetoes,
        },
        "infra": {
            "enable_hyde": bool(cfg.use_hyde),
            "enable_query_expansion": bool(cfg.use_query_expansion),
            "enable_multi_hop": bool(cfg.use_multi_hop),
        },
        "routing_decision": {
            "use_hyde": decision.use_hyde,
            "use_query_expansion": decision.use_query_expansion,
            "use_multi_hop": decision.use_multi_hop,
            "use_entity_fallback": decision.use_entity_fallback,
            "budget_reason": decision.budget_reason,
            "prompt_variant": decision.prompt_variant,
            "answer_shape": decision.answer_shape,
            "steps": decision.steps,
            "reasons": decision.reasons,
        },
        "inline_shadow": inline_shadow,
    }
```

Delete the now-unused `_shadow_routing` function entirely. Leave `decision_execution_dict` and `_prompt_variant` unchanged.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_control_routing.py -q`
Expected: PASS.

Do **not** commit yet. This task intentionally changes the `build_routing_trace` signature; the planner and observability tests are rewired in Task 3. Tasks 2 and 3 land together so there is no intermediate commit where `query_plan_node` passes the old `would_be_decision` argument into the new `inline_shadow` slot.

---

### Task 3: Runtime flags + planner wiring

**Files:**
- Modify: `backend/app/core/runtime_settings.py:24`
- Modify: `backend/app/rag/query/planner.py:60-94`
- Test: `backend/tests/unit/test_query_planner.py`
- Test: `backend/tests/unit/test_query_stats.py`

- [ ] **Step 1: Register the runtime-flag defaults**

In `backend/app/core/runtime_settings.py`, immediately after the line `_DEFAULTS.update(_build_query_defaults())` (line 24), add:

```python
_DEFAULTS.update(
    {
        "intent.inline_enabled": "false",
        "intent.active_mode": "false",
    }
)
```

- [ ] **Step 2: Fix the existing node test and write the new flag tests**

In `backend/tests/unit/test_query_planner.py`, first **replace** the three `shadow_routing` assertions in `test_query_plan_node_returns_plain_dict` (current lines 175-177) with:

```python
    assert out["routing_trace"]["inline_shadow"]["ran"] is False
    assert out["routing_trace"]["inline_shadow"]["fallback_reason"] == "none"
```

Then append the flag-driven tests:

```python
from app.core.runtime_settings import runtime_settings
from app.rag.query.control import llm_classifier
from app.rag.query.control.llm_classifier import ClassifyResult, LlmMarkers


def _set_flags(monkeypatch, *, inline, active):
    monkeypatch.setitem(runtime_settings._cache, "intent.inline_enabled", "true" if inline else "false")
    monkeypatch.setitem(runtime_settings._cache, "intent.active_mode", "true" if active else "false")


def _divergent_high(reason="none", markers=True):
    payload = LlmMarkers(needs_synthesis=True, needs_discovery=False, confidence="high", reasons=["x"])
    return lambda q, d: ClassifyResult(
        markers=payload if markers else None, fallback_reason=reason, latency_ms=5
    )


# A single-entity lookup whose deterministic intent is non-synthesis; the stub
# flips needs_synthesis=True, which changes answer_shape + budget => divergent route.
_STATE = {"query": "报销标准是什么？", "entity_mode": "single"}
_CONFIG = {"configurable": {"query_config": QueryConfig()}}


def test_inline_on_active_off_preserves_plan(monkeypatch):
    monkeypatch.setattr(llm_classifier, "classify_intent_inline", _divergent_high())
    baseline = query_plan_node(_STATE, _CONFIG)["query_plan"]

    _set_flags(monkeypatch, inline=True, active=False)
    out = query_plan_node(_STATE, _CONFIG)
    assert out["query_plan"] == baseline  # byte-for-byte 2A while inert
    assert out["routing_trace"]["inline_shadow"]["ran"] is True
    assert out["routing_trace"]["inline_shadow"]["activatable_diverged"] is True


def test_active_mode_drives_gated_route_and_budget(monkeypatch):
    monkeypatch.setattr(llm_classifier, "classify_intent_inline", _divergent_high())
    baseline = query_plan_node(_STATE, _CONFIG)["query_plan"]

    _set_flags(monkeypatch, inline=True, active=True)
    out = query_plan_node(_STATE, _CONFIG)
    assert out["query_plan"]["use_query_expansion"] != baseline["use_query_expansion"] or \
        out["query_plan"]["budget"] != baseline["budget"]
    # emitted intent now reflects the merged synthesis proposal
    assert out["routing_trace"]["routing_decision"]["answer_shape"] == "bullets_or_table"
    assert out["routing_trace"]["intent"]["source"] == "llm_escalated"


def test_failure_fallback_high_det_confidence_never_activates(monkeypatch):
    # det for a broad query is high-confidence; a failed classifier must NOT activate.
    state = {"query": "哪些公司提到了安全计划？", "entity_mode": "broad"}
    monkeypatch.setattr(
        llm_classifier, "classify_intent_inline", _divergent_high(reason="timeout", markers=False)
    )
    baseline = query_plan_node(state, _CONFIG)["query_plan"]

    _set_flags(monkeypatch, inline=True, active=True)
    out = query_plan_node(state, _CONFIG)
    assert out["query_plan"] == baseline  # pristine deterministic route
    shadow = out["routing_trace"]["inline_shadow"]
    assert shadow["fallback_used"] is True
    assert shadow["fallback_reason"] == "timeout"
    assert shadow["activatable_diverged"] is False
    assert out["routing_trace"]["intent"]["fallback_used"] is False  # emitted intent is det


def test_kill_switch_does_not_call_classifier(monkeypatch):
    calls = []
    monkeypatch.setattr(
        llm_classifier, "classify_intent_inline",
        lambda q, d: calls.append(1) or ClassifyResult(None, "none", 0),
    )
    _set_flags(monkeypatch, inline=False, active=False)
    out = query_plan_node(_STATE, _CONFIG)
    assert calls == []
    assert out["routing_trace"]["inline_shadow"]["ran"] is False
```

In `backend/tests/unit/test_query_stats.py`, replace the remaining `shadow_routing` fixture/assertions with the new inactive inline-shadow shape:

```python
"inline_shadow": {
    "ran": False,
    "fallback_reason": "none",
},
```

and assert:

```python
assert trace["inline_shadow"]["ran"] is False
assert trace["inline_shadow"]["fallback_reason"] == "none"
```

This applies to both the hand-built routing-trace passthrough test and the end-to-end `query_plan_node -> resolved_settings` test.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_query_planner.py -q`
Expected: FAIL — the planner still has the old `build_routing_trace(..., would_be_decision)` call site and has no `_inline_intent` / flag wiring yet.

- [ ] **Step 4: Rewire the planner**

In `backend/app/rag/query/planner.py`, replace `query_plan_node` (lines 60-74) and `_resolve_routing` (lines 82-94) and add the three helpers. New `query_plan_node`:

```python
def query_plan_node(state: QueryState, config: RunnableConfig) -> dict:
    """Resolve high-level query controls into one plan plus routing trace."""
    from app.rag.query.control.routing import build_routing_trace, inactive_inline_shadow

    cfg = get_query_config(config)
    query = require_query(state)
    entity_mode = state.get("entity_mode", "none")
    matched = list(state.get("matched_entities") or [])
    flavor, breadth, det_intent, det_decision, det_budget = _resolve_routing(
        query, entity_mode, matched, cfg
    )
    det_bundle = (det_intent, det_decision, det_budget)

    if _intent_flag("intent.inline_enabled"):
        gated_bundle, inline_shadow = _inline_intent(query, det_bundle, breadth, cfg)
    else:
        gated_bundle, inline_shadow = det_bundle, inactive_inline_shadow()

    emitted_bundle = gated_bundle if _intent_flag("intent.active_mode") else det_bundle
    emitted_intent, emitted_decision, emitted_budget = emitted_bundle

    plan = _plan_from_routing(flavor, breadth, emitted_decision, emitted_budget, cfg)
    return {
        "query_plan": asdict(plan),
        "routing_trace": build_routing_trace(
            emitted_intent, breadth, cfg, emitted_decision, inline_shadow
        ),
    }
```

New `_resolve_routing` (returns the same 5-tuple shape, now via the bundle helper so `build_query_plan` is unaffected):

```python
def _resolve_routing(query: str, entity_mode: str, matched_entities: list[str], cfg: QueryConfig):
    """Compute the deterministic routing pieces, shared by node + direct plan building."""
    from app.rag.query.control.breadth import resolve_breadth
    from app.rag.query.control.inferred import infer_signals

    flavor = _normalize_flavor(cfg.retrieval_flavor)
    breadth = resolve_breadth(flavor)
    inferred = infer_signals(query, entity_mode, matched_entities)
    det_intent, decision, budget = _route_bundle_for(inferred, breadth, cfg)
    return flavor, breadth, det_intent, decision, budget
```

Add the three new helpers (place them just below `_resolve_routing`):

```python
def _route_bundle_for(intent, breadth: str, cfg: QueryConfig):
    """Resolve one planner routing bundle: (intent, decision, budget)."""
    from app.rag.query.control.budget import resolve_budget_profile
    from app.rag.query.control.routing import derive_routing_decision

    budget = resolve_budget_profile(breadth, intent.entity_scope, intent.needs_synthesis, cfg)
    decision = derive_routing_decision(intent, breadth, cfg, budget_reason=budget.reason)
    return intent, decision, budget


def _intent_flag(key: str) -> bool:
    """Read a runtime kill-switch flag (sync, cached)."""
    from app.core.runtime_settings import runtime_settings

    return runtime_settings.get_cached(key).strip().lower() == "true"


def _inline_intent(query: str, det_bundle: tuple, breadth: str, cfg: QueryConfig):
    """Dark-wiring seam (excised wholesale in 2D): classify inline, merge, gate, shadow.

    Returns (gated_bundle, inline_shadow).
    """
    from app.rag.query.control.inferred import merge_intent
    from app.rag.query.control.llm_classifier import classify_intent_inline
    from app.rag.query.control.routing import build_inline_shadow, trust_gate_bundle

    det_intent = det_bundle[0]
    result = classify_intent_inline(query, det_intent)
    merged = merge_intent(det_intent, result.markers)
    merged_bundle = _route_bundle_for(merged, breadth, cfg)
    gated_bundle = trust_gate_bundle(merged_bundle, det_bundle)
    inline_shadow = build_inline_shadow(result, merged_bundle, det_bundle)
    return gated_bundle, inline_shadow
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_query_planner.py tests/unit/test_query_stats.py -q`
Expected: PASS.

- [ ] **Step 6: Run the full unit suite for regressions**

Run: `python -m pytest tests/unit -q`
Expected: PASS. (Characterization tests in `test_planner_characterization.py` confirm the default-flags plan is unchanged.)

- [ ] **Step 7: Commit Tasks 2 and 3 together**

```bash
git add backend/app/core/runtime_settings.py \
  backend/app/rag/query/control/routing.py \
  backend/app/rag/query/planner.py \
  backend/tests/unit/test_control_routing.py \
  backend/tests/unit/test_query_planner.py \
  backend/tests/unit/test_query_stats.py
git commit -m "feat(2C-2): bundle inline-shadow routing behind kill switches

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Offline shadow-gate report

**Files:**
- Create: `backend/scripts/report_inline_shadow.py`
- Test: `backend/tests/unit/test_inline_shadow_report.py`

- [ ] **Step 1: Write the failing aggregation test**

Create `backend/tests/unit/test_inline_shadow_report.py`. Import the script **inside** each test
(deferred), matching the working pattern in `test_routing_golden_set_fixture.py:50` — `scripts` has no
`__init__.py`, so a module-top import can fail at collection time:

```python
def _shadow(reason="none", latency=100, proposal=False, activatable=False, ran=True):
    return {
        "ran": ran,
        "fallback_reason": reason,
        "latency_ms": latency,
        "proposal_diverged": proposal,
        "activatable_diverged": activatable,
    }


def test_aggregate_partitions_reasons_and_gates():
    from scripts.report_inline_shadow import aggregate_inline_shadow

    rows = [
        _shadow(reason="none", latency=100, proposal=True, activatable=True),
        _shadow(reason="none", latency=200, proposal=True, activatable=False),
        _shadow(reason="timeout", latency=6000),
        _shadow(reason="error", latency=300),
        _shadow(reason="parse_fail", latency=150),
        _shadow(ran=False),  # not counted
    ]
    summary = aggregate_inline_shadow(rows)
    assert summary["volume"] == 5
    assert summary["classifier_error_rate"] == 0.4   # (timeout+error)/5
    assert summary["parse_fail_rate"] == 0.2
    assert summary["fallback_rate"] == 0.6
    assert summary["activatable_divergence_rate"] == 0.2
    assert summary["proposal_divergence_rate"] == 0.4
    assert summary["latency_ms_p95"] == 6000
    assert summary["gates"]["classifier_error_rate<=0.01"] is False
    assert summary["gates"]["volume>=200"] is False


def test_aggregate_empty_is_safe():
    from scripts.report_inline_shadow import aggregate_inline_shadow

    summary = aggregate_inline_shadow([])
    assert summary["volume"] == 0
    assert summary["classifier_error_rate"] == 0.0
    assert summary["gates"]["volume>=200"] is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/unit/test_inline_shadow_report.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.report_inline_shadow'`.

- [ ] **Step 3: Implement the report script**

Create `backend/scripts/report_inline_shadow.py`:

```python
"""Offline shadow-gate report for Design 2C-2 (inline shadow).

Reads inline_shadow records from query_run_stats and prints the 2C-3 go/no-go gate.
Standalone — archived after the activation flip; never imported by live code.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from typing import Any

from app.config import settings


def aggregate_inline_shadow(shadows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate inline_shadow dicts into the 2C-3 gate metrics. Pure function."""
    ran = [s for s in shadows if s.get("ran")]
    total = len(ran)

    def rate(n: int) -> float:
        return round(n / total, 4) if total else 0.0

    reasons = [str(s.get("fallback_reason", "none")) for s in ran]
    timeouts = sum(1 for r in reasons if r == "timeout")
    errors = sum(1 for r in reasons if r == "error")
    parse_fails = sum(1 for r in reasons if r == "parse_fail")

    latencies = sorted(int(s.get("latency_ms", 0)) for s in ran)
    p95 = latencies[int(round(0.95 * (len(latencies) - 1)))] if latencies else 0

    activatable = sum(1 for s in ran if s.get("activatable_diverged"))
    proposal = sum(1 for s in ran if s.get("proposal_diverged"))

    summary: dict[str, Any] = {
        "volume": total,
        "classifier_error_rate": rate(timeouts + errors),
        "parse_fail_rate": rate(parse_fails),
        "fallback_rate": rate(timeouts + errors + parse_fails),
        "latency_ms_p95": p95,
        "proposal_divergence_rate": rate(proposal),
        "activatable_divergence_rate": rate(activatable),
    }
    summary["gates"] = {
        "classifier_error_rate<=0.01": summary["classifier_error_rate"] <= 0.01,
        "parse_fail_rate<=0.02": summary["parse_fail_rate"] <= 0.02,
        "latency_ms_p95<=6000": summary["latency_ms_p95"] <= 6000,
        "volume>=200": total >= 200,
    }
    return summary


def _json_obj(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _load_shadows(db_path: str, *, since: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (all_shadows, activatable_rows) from query_run_stats."""
    query = "SELECT id, query, settings_json, created_at FROM query_run_stats"
    params: tuple[Any, ...] = ()
    if since:
        query += " WHERE created_at >= ?"
        params = (since,)
    query += " ORDER BY created_at DESC"
    shadows: list[dict[str, Any]] = []
    activatable_rows: list[dict[str, Any]] = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for row in conn.execute(query, params).fetchall():
            trace = _json_obj(_json_obj(row["settings_json"]).get("routing_trace"))
            shadow = _json_obj(trace.get("inline_shadow"))
            if not shadow:
                continue
            shadows.append(shadow)
            if shadow.get("activatable_diverged"):
                activatable_rows.append(
                    {"id": row["id"], "query": row["query"], "inline_shadow": shadow}
                )
    return shadows, activatable_rows


def main() -> None:
    args = _parse_args()
    shadows, activatable_rows = _load_shadows(args.db, since=args.since)
    summary = aggregate_inline_shadow(shadows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nactivatable_diverged rows for manual audit: {len(activatable_rows)}")
    for row in activatable_rows[: args.audit_limit]:
        print(json.dumps(row, ensure_ascii=False))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report Design 2C-2 inline-shadow gate")
    parser.add_argument("--db", default=settings.DATABASE_PATH, help="SQLite database path")
    parser.add_argument("--since", default=None, help="Only rows at/after this created_at")
    parser.add_argument("--audit-limit", type=int, default=50, help="Max activatable rows to print")
    return parser.parse_args()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/unit/test_inline_shadow_report.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/report_inline_shadow.py backend/tests/unit/test_inline_shadow_report.py
git commit -m "feat(2C-2): offline inline-shadow gate report

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Manual dark-launch run + gate review (no code)

This task produces the production-shadow evidence; it runs against a live LLM + the real DB, so it is manual (like the 2C-1 scorer run). Do **not** flip `intent.active_mode`.

- [ ] **Step 1: Enable inline-only via the settings API (dark launch)**

Set `intent.inline_enabled = "true"`, keep `intent.active_mode = "false"` through the running app's settings API (the same path the admin UI uses). Confirm with a single query that the response is unchanged and `routing_trace.inline_shadow.ran` is `true` in the stats row.

- [ ] **Step 2: Drive representative live traffic**

Run the existing non-eval live-query set (the same ~12 queries used to smoke 2B), plus enough real/manual queries to clear the `volume >= 200` gate over the observation window. Each query writes an `inline_shadow` row into `query_run_stats` automatically (no code change — it rides `routing_trace`).

- [ ] **Step 3: Run the report and review the gate**

Run: `python -m scripts.report_inline_shadow --since <window-start>`
Expected: a JSON summary with `gates`. Confirm `classifier_error_rate <= 0.01`, `parse_fail_rate <= 0.02`, `latency_ms_p95 <= 6000`, `volume >= 200`. Manually inspect every printed `activatable_diverged` row — these are exactly the queries that will change route at 2C-3; confirm each proposed flip is one you'd want.

**2C-3 supersession note (2026-06-13).** Do not carry the `classifier_error_rate <= 0.01` and
`volume >= 200` checks forward as hard 2C-3 activation gates. The 2C-3 dry run/dark launch showed
they are unrealistic for this local/manual deployment and slow remote classifier endpoint. In 2C-3,
timeout/error rate and volume are reported lift/capacity diagnostics; route safety, Hit@K, applicable
answer quality, inline latency p95, and audit of `activatable_diverged` rows are the hard gates.

- [ ] **Step 4: Record the result**

Append the summary JSON + audit notes to the 2C-2 closeout (a short note in the PR / a `data/` artifact, matching how 2B/2C-1 results were recorded). For the original 2C-2 plan, a hard-gate failure meant "stop and file findings"; after the 2C-3 supersession above, those findings feed the revised 2C-3 gate model rather than automatically blocking all 2C-3 work.

---

## Self-review

**Spec coverage:**
- Inline timeout setting, `ClassifyResult` envelope, `_invoke_classifier` shared seam, `_is_timeout` taxonomy, `classify_intent_llm` delegation → **Task 1**.
- `activatable`, `trust_gate_bundle`, `build_inline_shadow` (proposal_execution/proposal_diverged/activatable_diverged), `inactive_inline_shadow`, trace rework → **Task 2**.
- Runtime flags in `_DEFAULTS`, `_intent_flag`, `_route_bundle_for`, `_inline_intent` seam, bundle wiring, byte-for-byte preservation / active wiring / fallback-never-activates / kill switch → **Task 3** (covers spec Testing 1–5).
- Offline report + slices/gates (spec Testing 6) → **Task 4**.
- Manual run + audit → **Task 5**.
- WARN counters (spec Failure §4): emitted as structured `logger.warning(... fallback=%s latency_ms=%d ...)` in `classify_intent_inline` (Task 1, Step 4).
- Excisable seam (`_inline_intent`) is the single deletion point for 2D → Task 3.

**Type consistency:** bundles are `(intent, decision, budget)` tuples throughout; the planner-local `_route_bundle_for` returns that full bundle, while the existing offline `control/route_scoring.py::route_for_intent` remains scorer-only and returns `RoutingDecision`; `ClassifyResult` fields (`markers`, `fallback_reason`, `latency_ms`) are produced in Task 1 and read identically in `build_inline_shadow` (Task 2) and the report (Task 4); flag keys `intent.inline_enabled` / `intent.active_mode` match across `_DEFAULTS`, `_intent_flag`, and tests.

**Placeholder scan:** none — every code step shows complete code and exact commands.

**Note on `build_query_plan`:** it still calls `_resolve_routing` and stays purely deterministic (no flags, no inline) — only `query_plan_node` runs the seam. `get_query_plan`'s fallback path is therefore unchanged.
