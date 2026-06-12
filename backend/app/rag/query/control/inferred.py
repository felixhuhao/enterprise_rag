"""Deterministic inferred tier for Design 1."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from app.rag.query.intent_markers import has_synthesis_marker
from app.rag.query.multi_hop import DISCOVERY_KEYWORDS, RESPONSIBILITY_HOP_KEYWORDS

if TYPE_CHECKING:
    from app.rag.query.control.llm_classifier import LlmMarkers

EntityScope = Literal["single", "multi", "broad", "none"]
Confidence = Literal["high", "medium", "low"]
CONFIDENCE_LEVELS: set[Confidence] = {"high", "medium", "low"}

_ENTITY_MODE_TO_SCOPE: dict[str, EntityScope] = {
    "single": "single",
    "multi_explicit": "multi",
    "broad": "broad",
    "none": "none",
}
_DISCOVERY_GATE_KEYWORDS = DISCOVERY_KEYWORDS + RESPONSIBILITY_HOP_KEYWORDS


@dataclass(frozen=True)
class InferredSignals:
    entity_scope: EntityScope
    needs_synthesis: bool
    needs_discovery: bool
    needs_multi_hop: bool
    requested_format: str | None = None
    confidence: Confidence = "high"
    reasons: list[str] = field(default_factory=list)
    source: str = "deterministic"
    fallback_used: bool = False


def _confidence(entity_scope: str, has_routing_marker: bool) -> Confidence:
    """Deterministic confidence ladder v1 for Design 2A."""
    grounded = entity_scope in ("single", "multi")
    if entity_scope == "broad" or (grounded and has_routing_marker):
        return "high"
    if grounded or has_routing_marker:
        return "medium"
    return "low"


def infer_signals(query: str, entity_mode: str, matched_entities: list[str]) -> InferredSignals:
    """Fold current deterministic query-shape checks into one inferred signal object."""
    # Design 1 intentionally does not infer from entity names; this is carried
    # in the signature for the Design 2 classifier.
    del matched_entities
    scope = _ENTITY_MODE_TO_SCOPE.get(entity_mode, "none")
    needs_synthesis = has_synthesis_marker(query)
    has_discovery_kw = any(kw in query for kw in _DISCOVERY_GATE_KEYWORDS)
    needs_multi_hop = scope in ("broad", "none") and has_discovery_kw

    reasons: list[str] = []
    if needs_synthesis:
        reasons.append("synthesis:marker")
    if has_discovery_kw:
        reasons.append("discovery:keyword")
    reasons.append(f"entity_scope:{scope}")
    has_routing_marker = needs_synthesis or has_discovery_kw

    return InferredSignals(
        entity_scope=scope,
        needs_synthesis=needs_synthesis,
        needs_discovery=has_discovery_kw,
        needs_multi_hop=needs_multi_hop,
        requested_format=None,
        confidence=_confidence(scope, has_routing_marker),
        reasons=reasons,
        source="deterministic",
        fallback_used=False,
    )


def merge_intent(deterministic: InferredSignals, llm: "LlmMarkers | None") -> InferredSignals:
    """Merge optional LLM markers into deterministic intent."""
    if llm is None:
        return dataclasses.replace(
            deterministic,
            source="deterministic",
            fallback_used=True,
        )

    needs_multi_hop = deterministic.entity_scope in ("broad", "none") and llm.needs_discovery
    llm_reasons = [f"llm:{reason}" for reason in llm.reasons]
    return dataclasses.replace(
        deterministic,
        needs_synthesis=llm.needs_synthesis,
        needs_discovery=llm.needs_discovery,
        needs_multi_hop=needs_multi_hop,
        confidence=llm.confidence,
        reasons=[*deterministic.reasons, *llm_reasons],
        source="llm_escalated",
        fallback_used=False,
    )
