"""Shared query intent markers used by planner and prompt construction."""

from __future__ import annotations

SYNTHESIS_QUERY_MARKERS = (
    "比较",
    "关联",
    "区别",
    "异同",
    "一致",
    "不同",
    "分别",
    "各自",
    "对比",
)


def has_synthesis_marker(query: str) -> bool:
    return any(marker in query for marker in SYNTHESIS_QUERY_MARKERS)
