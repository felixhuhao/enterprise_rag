from app.rag.chunking.enrichment import build_search_text
from app.rag.chunking.structured_tag_registry import (
    MAX_STRUCTURED_TAGS,
    apply_structured_tag_override,
    get_structured_tag_definition,
    normalize_structured_tags,
    structured_tag_label,
)


def test_registry_exposes_builtin_label_and_metadata():
    definition = get_structured_tag_definition("approval_rule")

    assert definition is not None
    assert definition.label == "审批规则"
    assert definition.priority == 20
    assert definition.scope == "chunk"
    assert definition.profile == "enterprise_policy"
    assert structured_tag_label("approval_rule") == "审批规则"


def test_apply_structured_tag_override_uses_only_provided_values():
    definition = get_structured_tag_definition("approval_rule")
    assert definition is not None

    effective = apply_structured_tag_override(
        definition,
        {
            "label": "审批要求",
            "description": None,
            "enabled": 0,
            "ui_visible": 1,
        },
    )

    assert effective.label == "审批要求"
    assert effective.description == definition.description
    assert effective.enabled is False
    assert effective.ui_visible is True


def test_normalize_structured_tags_filters_unknown_and_dedupes():
    tags = normalize_structured_tags([
        "approval_rule",
        "unknown_tag",
        "approval_rule",
        "",
        None,
        "deadline_rule",
    ])

    assert tags == ["approval_rule", "deadline_rule"]


def test_normalize_structured_tags_caps_registered_tags():
    tags = normalize_structured_tags([
        "amount_threshold",
        "approval_rule",
        "deadline_rule",
        "training_budget",
        "payment_rule",
    ])

    assert tags == [
        "amount_threshold",
        "approval_rule",
        "training_budget",
        "deadline_rule",
    ]
    assert len(tags) == MAX_STRUCTURED_TAGS


def test_normalize_structured_tags_sorts_by_priority_before_cap():
    tags = normalize_structured_tags([
        "payment_rule",
        "deadline_rule",
        "approval_rule",
        "amount_threshold",
        "training_budget",
    ])

    assert tags == [
        "amount_threshold",
        "approval_rule",
        "training_budget",
        "deadline_rule",
    ]


def test_unknown_structured_tags_do_not_enter_search_text():
    search_text = build_search_text({
        "content": "",
        "section_title": "",
        "keywords": [],
        "structured_tags": ["unknown_tag"],
    })

    assert "unknown_tag" not in search_text
