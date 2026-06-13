def _shadow(reason="none", latency=100, proposal=False, activatable=False, ran=True):
    return {
        "ran": ran,
        "fallback_reason": reason,
        "latency_ms": latency,
        "proposal_diverged": proposal,
        "activatable_diverged": activatable,
    }


def test_aggregate_partitions_reasons_and_gates():
    from scripts.report_inline_shadow import aggregate_inline_shadow

    rows = [
        _shadow(reason="none", latency=100, proposal=True, activatable=True),
        _shadow(reason="none", latency=200, proposal=True, activatable=False),
        _shadow(reason="timeout", latency=6000),
        _shadow(reason="error", latency=300),
        _shadow(reason="parse_fail", latency=150),
        _shadow(ran=False),
    ]

    summary = aggregate_inline_shadow(rows)

    assert summary["volume"] == 5
    assert summary["classifier_error_rate"] == 0.4
    assert summary["parse_fail_rate"] == 0.2
    assert summary["fallback_rate"] == 0.6
    assert summary["activatable_divergence_rate"] == 0.2
    assert summary["proposal_divergence_rate"] == 0.4
    assert summary["latency_ms_p95"] == 6000
    assert summary["gates"]["classifier_error_rate<=0.01"] is False
    assert summary["gates"]["volume>=200"] is False


def test_aggregate_empty_is_safe():
    from scripts.report_inline_shadow import aggregate_inline_shadow

    summary = aggregate_inline_shadow([])

    assert summary["volume"] == 0
    assert summary["classifier_error_rate"] == 0.0
    assert summary["gates"]["volume>=200"] is False
