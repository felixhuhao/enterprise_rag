"""Offline LLM intent classifier for Design 2B."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

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


INTENT_CLASSIFIER_SYSTEM = """\
You classify routing intent for Chinese/English enterprise-document questions.
Decide only:
- needs_synthesis: comparison, relationship, causal, cross-document, cross-entity, or temporal synthesis.
- needs_discovery: finding which entities/people/documents relate to a topic, responsibility, owner, or condition.

Do not classify entity_scope. Do not extract requested output format.
Return strict JSON only:
{"needs_synthesis":false,"needs_discovery":false,"confidence":"high","reasons":[]}
"""


def classify_intent_llm(query: str, deterministic: InferredSignals) -> LlmMarkers | None:
    """Return LLM routing markers, or None on any call/parse/contract failure."""
    try:
        llm = ChatOpenAI(
            model=_classifier_model(),
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            timeout=settings.INTENT_CLASSIFIER_TIMEOUT,
            max_retries=1,
            temperature=settings.INTENT_CLASSIFIER_TEMPERATURE,
            max_tokens=settings.INTENT_CLASSIFIER_MAX_TOKENS,
        )
        response = llm.invoke(
            [
                SystemMessage(content=INTENT_CLASSIFIER_SYSTEM),
                HumanMessage(content=_classifier_user_prompt(query, deterministic)),
            ],
            timeout=settings.INTENT_CLASSIFIER_TIMEOUT,
        )
        raw = response.content if hasattr(response, "content") else str(response)
        return parse_llm_markers(str(raw or ""))
    except Exception:
        logger.warning("Intent classifier LLM call failed", exc_info=True)
        return None


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

Examples:
Q: 星辰科技和远景能源的差旅住宿标准有什么区别？
{{"needs_synthesis":true,"needs_discovery":false,"confidence":"high","reasons":["implicit comparison across entities"]}}

Q: 谁负责供应商付款审批？
{{"needs_synthesis":false,"needs_discovery":true,"confidence":"high","reasons":["responsibility discovery"]}}

Q: 星辰科技的报销标准是多少？
{{"needs_synthesis":false,"needs_discovery":false,"confidence":"high","reasons":["plain entity lookup"]}}

Return JSON for the question only.
"""
