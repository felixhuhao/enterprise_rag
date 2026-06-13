import json
from collections import Counter
from pathlib import Path

from app.rag.query.control.inferred import infer_signals

CORPUS = Path(__file__).resolve().parents[3] / "data" / "routing_golden_set_v1.jsonl"
FUZZY = {
    "implicit_synthesis",
    "paraphrase",
    "discovery_unspecified",
    "discovery_no_keyword",
    "multi_hop_altphrase",
}
VALID_CATEGORIES = FUZZY | {"clear_control"}


def _load():
    return [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_corpus_size_and_categories():
    cases = _load()
    assert 35 <= len(cases) <= 48, f"expected ~40 cases, got {len(cases)}"
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids)), "duplicate ids"

    by_category = Counter(case["category"] for case in cases)
    for case in cases:
        assert case["category"] in VALID_CATEGORIES, case["category"]
        assert case["case_class"] in {"clear", "ambiguous"}
        assert case["retrieval_breadth"] in {"precise", "balanced", "broad"}
    for category in FUZZY:
        assert 6 <= by_category[category] <= 8, f"{category}: expected 6-8, got {by_category[category]}"
    assert 5 <= by_category["clear_control"] <= 8, (
        f"clear_control: expected 5-8, got {by_category['clear_control']}"
    )


def test_every_case_entity_scope_is_consistent():
    for case in _load():
        det = infer_signals(case["query"], case["entity_mode"], case.get("matched_entities", []))
        assert det.entity_scope == case["expected_intent"]["entity_scope"], (
            f"{case['id']}: deterministic scope {det.entity_scope} != "
            f"labeled {case['expected_intent']['entity_scope']}"
        )


def test_scorer_default_corpus_points_to_root_data():
    from scripts.score_routing_golden_set import DEFAULT_CORPUS

    assert DEFAULT_CORPUS.resolve() == CORPUS.resolve()


def test_clear_cases_have_full_markers_ambiguous_have_acceptable():
    for case in _load():
        expected = case["expected_intent"]
        assert "entity_scope" in expected
        if case["case_class"] == "clear":
            assert "needs_synthesis" in expected
            assert "needs_discovery" in expected
        else:
            assert case.get("acceptable") == "expected_route_or_safe_default"


def test_fuzzy_categories_include_ambiguous_safety_cases():
    cases = _load()
    for category in FUZZY:
        ambiguous_count = sum(
            1 for case in cases
            if case["category"] == category and case["case_class"] == "ambiguous"
        )
        assert 2 <= ambiguous_count <= 3, f"{category}: expected 2-3 ambiguous, got {ambiguous_count}"
