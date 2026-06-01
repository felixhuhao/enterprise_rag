"""Controlled registry for chunk-level structured tags."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
import sqlite3
import threading

from app.config import settings

MAX_STRUCTURED_TAGS = 4


@dataclass(frozen=True)
class StructuredTagDefinition:
    tag_key: str
    label: str
    description: str
    priority: int
    scope: str = "chunk"
    profile: str = "enterprise_policy"
    enabled: bool = True
    ui_visible: bool = True


BUILTIN_STRUCTURED_TAGS: tuple[StructuredTagDefinition, ...] = (
    StructuredTagDefinition(
        tag_key="amount_threshold",
        label="金额阈值",
        description="包含金额表达和阈值条件。",
        priority=10,
    ),
    StructuredTagDefinition(
        tag_key="approval_rule",
        label="审批规则",
        description="包含审批、审核、签字或批准要求。",
        priority=20,
    ),
    StructuredTagDefinition(
        tag_key="training_budget",
        label="培训预算",
        description="包含培训费用、预算、报销或审批信息。",
        priority=30,
    ),
    StructuredTagDefinition(
        tag_key="deadline_rule",
        label="时限规则",
        description="包含提交、报告、响应或处理时限。",
        priority=40,
    ),
    StructuredTagDefinition(
        tag_key="security_incident_rule",
        label="安全事件",
        description="包含安全事件、数据泄露、设备丢失等信息安全事件处理要求。",
        priority=45,
    ),
    StructuredTagDefinition(
        tag_key="payment_rule",
        label="付款规则",
        description="包含付款或支付要求。",
        priority=50,
    ),
    StructuredTagDefinition(
        tag_key="reimbursement_rule",
        label="报销规则",
        description="包含费用报销要求。",
        priority=60,
    ),
    StructuredTagDefinition(
        tag_key="procurement_rule",
        label="采购规则",
        description="包含采购或供应商规则。",
        priority=70,
    ),
    StructuredTagDefinition(
        tag_key="budget_rule",
        label="预算规则",
        description="包含预算金额或预算审批规则。",
        priority=80,
    ),
)

_REGISTRY = {definition.tag_key: definition for definition in BUILTIN_STRUCTURED_TAGS}
_OVERRIDE_CACHE: dict[str, dict[str, object]] | None = None
_OVERRIDE_LOCK = threading.Lock()


def get_structured_tag_definition(tag_key: str) -> StructuredTagDefinition | None:
    definition = _REGISTRY.get(str(tag_key or ""))
    if not definition:
        return None
    return _apply_override(definition)


def get_builtin_structured_tag_definition(tag_key: str) -> StructuredTagDefinition | None:
    return _REGISTRY.get(str(tag_key or ""))


def list_structured_tag_definitions() -> list[StructuredTagDefinition]:
    return [get_structured_tag_definition(definition.tag_key) or definition for definition in BUILTIN_STRUCTURED_TAGS]


def structured_tag_label(tag_key: str) -> str:
    definition = get_structured_tag_definition(tag_key)
    return definition.label if definition else str(tag_key or "")


def is_registered_structured_tag(tag_key: str, profile: str = "enterprise_policy") -> bool:
    definition = get_structured_tag_definition(tag_key)
    if not definition or not definition.enabled:
        return False
    return definition.profile == profile


def normalize_structured_tags(
    tags: Iterable[object],
    profile: str = "enterprise_policy",
    max_tags: int = MAX_STRUCTURED_TAGS,
) -> list[str]:
    accepted: list[str] = []
    seen: set[str] = set()
    for value in tags:
        tag_key = str(value or "").strip()
        if not tag_key or tag_key in seen:
            continue
        if not is_registered_structured_tag(tag_key, profile=profile):
            continue
        seen.add(tag_key)
        accepted.append(tag_key)
    accepted.sort(key=_tag_priority)
    return accepted[:max_tags]


def _tag_priority(tag_key: str) -> int:
    definition = get_structured_tag_definition(tag_key)
    return definition.priority if definition else 9999


def invalidate_structured_tag_overrides() -> None:
    global _OVERRIDE_CACHE
    with _OVERRIDE_LOCK:
        _OVERRIDE_CACHE = None


def _apply_override(definition: StructuredTagDefinition) -> StructuredTagDefinition:
    override = _structured_tag_overrides().get(definition.tag_key)
    if not override:
        return definition
    values = {}
    for field in ("label", "description"):
        value = override.get(field)
        if value is not None:
            values[field] = str(value)
    for field in ("enabled", "ui_visible"):
        value = override.get(field)
        if value is not None:
            values[field] = bool(value)
    return replace(definition, **values)


def _structured_tag_overrides() -> dict[str, dict[str, object]]:
    global _OVERRIDE_CACHE
    with _OVERRIDE_LOCK:
        if _OVERRIDE_CACHE is None:
            _OVERRIDE_CACHE = _load_structured_tag_overrides()
        return _OVERRIDE_CACHE


def _load_structured_tag_overrides() -> dict[str, dict[str, object]]:
    db_path = Path(settings.DATABASE_PATH)
    if not db_path.exists():
        return {}
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT tag_key, label, description, enabled, ui_visible
                   FROM structured_tag_overrides"""
            ).fetchall()
    except sqlite3.Error:
        return {}
    return {
        str(row["tag_key"]): {
            "label": row["label"],
            "description": row["description"],
            "enabled": row["enabled"],
            "ui_visible": row["ui_visible"],
        }
        for row in rows
    }
