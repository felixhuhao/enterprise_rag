"""Deterministic inferred tier for Design 1."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.rag.query.intent_markers import has_synthesis_marker
from app.rag.query.multi_hop import DISCOVERY_KEYWORDS, RESPONSIBILITY_HOP_KEYWORDS

EntityScope = Literal["single", "multi", "broad", "none"]

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
    confidence: str = "high"
    reasons: list[str] = field(default_factory=list)


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

    return InferredSignals(
        entity_scope=scope,
        needs_synthesis=needs_synthesis,
        needs_discovery=has_discovery_kw,
        needs_multi_hop=needs_multi_hop,
        requested_format=None,
        confidence="high",
        reasons=reasons,
    )
