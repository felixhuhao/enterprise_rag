from scripts.eval_golden_set import _case_query_config, build_summary


def test_case_query_config_uses_preferred_flavor_and_strict():
    item = {"preferred_flavor": "recall", "strict_evidence": True}

    assert _case_query_config(item) == {
        "retrieval_flavor": "recall",
        "strict_evidence": True,
    }


def test_case_query_config_falls_back_to_source_config():
    item = {"source_config": {"retrieval_flavor": "discovery", "strict_evidence": True}}

    assert _case_query_config(item) == {
        "retrieval_flavor": "discovery",
        "strict_evidence": True,
    }


def test_case_query_config_normalizes_invalid_flavor():
    item = {"preferred_flavor": "wide", "strict_evidence": "false"}

    assert _case_query_config(item) == {
        "retrieval_flavor": "balanced",
        "strict_evidence": False,
    }


def test_summary_groups_by_actual_flavor_when_available():
    summary = build_summary([
        {
            "id": "case-1",
            "final_score": 1.0,
            "eval_type": "rule",
            "preferred_flavor": "balanced",
            "actual_retrieval_flavor": "recall",
            "strict_evidence": False,
        }
    ])

    assert "recall" in summary["per_flavor"]
    assert "balanced" not in summary["per_flavor"]
