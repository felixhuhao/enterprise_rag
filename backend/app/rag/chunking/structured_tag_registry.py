"""Controlled registry for chunk-level structured tags."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

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


def get_structured_tag_definition(tag_key: str) -> StructuredTagDefinition | None:
    return _REGISTRY.get(str(tag_key or ""))


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
