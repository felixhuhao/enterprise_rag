def _row(case_id, *, keys, hit5, hit10, expansion, activatable):
    return {
        "id": case_id,
        "hit_at_5": hit5,
        "hit_at_10": hit10,
        "rerank_results": [{"chunk_key": k, "document_id": f"doc-{k}"} for k in keys],
        "retrieval_step": {
            "query_plan": {
                "use_hyde": True,
                "use_query_expansion": expansion,
                "use_multi_hop": False,
                "fallback_policy": {"entity_filter_to_global": False},
                "retrieval_breadth": "balanced",
                "strict_evidence": False,
                "budget": {"search_limit": 10, "reason": "balanced_current_defaults"},
                "prompt_policy": {"template": "default"},
            },
            "routing_trace": {
                "routing_decision": {
                    "use_hyde": True,
                    "use_query_expansion": expansion,
                    "use_multi_hop": False,
                    "use_entity_fallback": False,
                    "budget_reason": "balanced_current_defaults",
                    "prompt_variant": "default",
                    "answer_shape": "prose",
                    "steps": [],
                },
                "inline_shadow": {"activatable_diverged": activatable},
            },
        },
    }


def test_comparator_flags_non_activatable_change_as_leak():
    from scripts.compare_activation_eval import compare_activation_runs

    off = {
        "a": _row("a", keys=["k1"], hit5=True, hit10=True, expansion=False, activatable=False),
        "b": _row("b", keys=["k1"], hit5=True, hit10=True, expansion=False, activatable=False),
        "c": _row("c", keys=["k1"], hit5=True, hit10=True, expansion=False, activatable=False),
        "d": _row("d", keys=["k1"], hit5=True, hit10=True, expansion=False, activatable=False),
    }
    on = {
        "a": _row("a", keys=["k2"], hit5=True, hit10=True, expansion=True, activatable=True),
        "b": _row("b", keys=["k9"], hit5=True, hit10=True, expansion=True, activatable=False),
        "c": _row("c", keys=["k1"], hit5=True, hit10=True, expansion=False, activatable=False),
        "d": _row("d", keys=["k8"], hit5=True, hit10=True, expansion=False, activatable=False),
    }

    summary = compare_activation_runs(off, on)

    assert summary["changed_ids"] == ["a", "b"]
    assert summary["route_changed_ids"] == ["a", "b"]
    assert summary["ranked_key_changed_ids"] == ["a", "b", "d"]
    assert summary["activatable_ids"] == ["a"]
    assert summary["leak_ids"] == ["b"]
    assert summary["gates"]["no_leak"] is False


def test_comparator_clean_when_only_activatable_change():
    from scripts.compare_activation_eval import compare_activation_runs

    off = {"a": _row("a", keys=["k1"], hit5=True, hit10=True, expansion=False, activatable=False)}
    on = {"a": _row("a", keys=["k2"], hit5=True, hit10=True, expansion=True, activatable=True)}

    summary = compare_activation_runs(off, on)

    assert summary["leak_ids"] == []
    assert summary["ranked_key_changed_ids"] == ["a"]
    assert summary["gates"]["no_leak"] is True


def test_comparator_flags_hit_regression():
    from scripts.compare_activation_eval import compare_activation_runs

    off = {"a": _row("a", keys=["k1"], hit5=True, hit10=True, expansion=False, activatable=False)}
    on = {"a": _row("a", keys=["k1"], hit5=False, hit10=True, expansion=False, activatable=False)}

    summary = compare_activation_runs(off, on)

    assert summary["hit_changed_ids"] == ["a"]
    assert summary["hit_regression_ids"] == ["a"]
    assert summary["gates"]["no_hit_regression"] is False
