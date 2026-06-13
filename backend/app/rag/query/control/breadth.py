"""Retrieval breadth: the user-policy tier, resolved from legacy flavor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RetrievalBreadth = Literal["precise", "balanced", "broad"]

VALID_BREADTHS = {"precise", "balanced", "broad"}

_FLAVOR_TO_BREADTH = {
    "exact": "precise",
    "balanced": "balanced",
    "recall": "broad",
    "discovery": "balanced",
}


def resolve_breadth(flavor: str) -> RetrievalBreadth:
    """Map a legacy retrieval_flavor, or already-migrated breadth, to breadth."""
    if flavor in VALID_BREADTHS:
        return flavor  # type: ignore[return-value]
    return _FLAVOR_TO_BREADTH.get(flavor, "balanced")  # type: ignore[return-value]


@dataclass(frozen=True)
class BreadthProfile:
    sets_hyde: bool
    sets_expansion: bool
    allows_fallback: bool
    permits_multi_hop: bool


BREADTH_PROFILES: dict[str, BreadthProfile] = {
    "precise": BreadthProfile(False, False, False, False),
    "balanced": BreadthProfile(True, False, True, True),
    "broad": BreadthProfile(False, True, True, True),
}
