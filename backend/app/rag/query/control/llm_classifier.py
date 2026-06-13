"""LLM intent classifier for Design 2B replay and 2C inline shadow routing."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.config import settings
from app.rag.query.control.inferred import CONFIDENCE_LEVELS, Confidence, InferredSignals
from app.rag.query.llm_json import parse_llm_json_object

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LlmMarkers:
    needs_synthesis: bool
    needs_discovery: bool
    confidence: Confidence
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ClassifyResult:
    markers: LlmMarkers | None
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


INTENT_CLASSIFIER_SYSTEM = """\
You classify routing intent for Chinese/English enterprise-document questions.
Decide only:
- needs_synthesis: comparison, relationship, causal, cross-document, cross-entity, or temporal synthesis.
- needs_discovery: finding which entities/people/documents relate to a topic, responsibility, owner, or condition.

Guidance:
- If the question asks which person, team, organization, level, category, or document becomes
  responsible, involved, applicable, or escalated-to, mark needs_discovery.
- If the question asks between/among named entities who owns or handles something, mark both
  needs_synthesis and needs_discovery.
- Use high confidence when a routing marker is clear enough to change retrieval; reserve medium for
  genuinely uncertain or underspecified routing intent.

Do not classify entity_scope. Do not extract requested output format.
Return strict JSON only:
{"needs_synthesis":false,"needs_discovery":false,"confidence":"high","reasons":[]}
"""


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


def _invoke_classifier(
    query: str,
    deterministic: InferredSignals,
    timeout: int,
    *,
    max_retries: int = 1,
) -> str:
    """Build the client, invoke, return raw content. Does not catch."""
    llm = ChatOpenAI(
        model=_classifier_model(),
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
        timeout=timeout,
        max_retries=max_retries,
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


def classify_intent_llm(query: str, deterministic: InferredSignals) -> LlmMarkers | None:
    """Offline entry point: markers or None on any call/parse/contract failure."""
    try:
        raw = _invoke_classifier(
            query,
            deterministic,
            settings.INTENT_CLASSIFIER_TIMEOUT,
            max_retries=1,
        )
        return _calibrate_confidence(parse_llm_markers(raw), deterministic)
    except Exception:
        logger.warning("Intent classifier LLM call failed", exc_info=True)
        return None


def classify_intent_inline(query: str, deterministic: InferredSignals) -> ClassifyResult:
    """Inline entry point: time the call and classify the failure reason."""
    start = time.monotonic()
    try:
        raw = _invoke_classifier(
            query,
            deterministic,
            settings.INTENT_CLASSIFIER_INLINE_TIMEOUT,
            max_retries=0,
        )
    except Exception as exc:
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


def parse_llm_markers(raw: str) -> LlmMarkers | None:
    """Parse and validate the LLM marker contract."""
    parsed = parse_llm_json_object(raw)
    if parsed is None:
        return None

    needs_synthesis = parsed.get("needs_synthesis")
    needs_discovery = parsed.get("needs_discovery")
    confidence = parsed.get("confidence")
    reasons = parsed.get("reasons")

    if not isinstance(needs_synthesis, bool) or not isinstance(needs_discovery, bool):
        return None
    if confidence not in CONFIDENCE_LEVELS:
        return None
    if not isinstance(reasons, list):
        return None

    clean_reasons = [reason.strip() for reason in reasons if isinstance(reason, str) and reason.strip()]
    return LlmMarkers(
        needs_synthesis=needs_synthesis,
        needs_discovery=needs_discovery,
        confidence=confidence,
        reasons=clean_reasons,
    )


def _calibrate_confidence(markers: LlmMarkers | None, deterministic: InferredSignals) -> LlmMarkers | None:
    """Prevent non-routing no-op classifications from becoming activatable."""
    if markers is None:
        return None
    if markers.confidence != "high":
        return markers
    if deterministic.confidence == "high":
        return markers
    if markers.needs_synthesis or markers.needs_discovery:
        return markers
    return replace(
        markers,
        confidence="medium",
        reasons=[*markers.reasons, "calibrated:no routing marker from non-high deterministic intent"],
    )


def _classifier_model() -> str:
    return settings.INTENT_CLASSIFIER_MODEL or settings.CHAT_MODEL


def _classifier_user_prompt(query: str, deterministic: InferredSignals) -> str:
    return f"""\
Question:
{query}

Deterministic context:
- entity_scope: {deterministic.entity_scope}
- deterministic_needs_synthesis: {str(deterministic.needs_synthesis).lower()}
- deterministic_needs_discovery: {str(deterministic.needs_discovery).lower()}
- deterministic_confidence: {deterministic.confidence}

Confidence contract:
- high means the routing implication is clear enough to drive retrieval.
- medium means plausible but not safe to activate without falling back.
- low means insufficient routing evidence.
- If you decline all routing markers on a medium/low deterministic case, prefer medium over high.

Examples:
Q: 星辰科技和远景能源的差旅住宿标准有什么区别？
{{"needs_synthesis":true,"needs_discovery":false,"confidence":"high","reasons":["implicit comparison across entities"]}}

Q: 谁负责供应商付款审批？
{{"needs_synthesis":false,"needs_discovery":true,"confidence":"high","reasons":["responsibility discovery"]}}

Q: 星辰科技的报销标准是多少？
{{"needs_synthesis":false,"needs_discovery":false,"confidence":"medium","reasons":["plain entity lookup"]}}

Return JSON for the question only.
"""
