def _shadow(reason="none", latency=100, proposal=False, activatable=False, ran=True, skip_reason=None):
    row = {
        "ran": ran,
        "fallback_reason": reason,
        "latency_ms": latency,
        "proposal_diverged": proposal,
        "activatable_diverged": activatable,
    }
    if skip_reason:
        row["skip_reason"] = skip_reason
    return row


def test_aggregate_partitions_reasons_and_gates():
    from scripts.report_inline_shadow import aggregate_inline_shadow

    rows = [
        _shadow(reason="none", latency=100, proposal=True, activatable=True),
        _shadow(reason="none", latency=200, proposal=True, activatable=False),
        _shadow(reason="timeout", latency=6000),
        _shadow(reason="error", latency=300),
        _shadow(reason="parse_fail", latency=150),
        _shadow(ran=False, skip_reason="high_confidence"),
    ]

    summary = aggregate_inline_shadow(rows)

    assert summary["observed_rows"] == 6
    assert summary["volume"] == 5
    assert summary["classifier_runs"] == 5
    assert summary["skipped_rows"] == 1
    assert summary["skip_reasons"] == {"high_confidence": 1}
    assert summary["classifier_run_rate"] == 0.8333
    assert summary["skip_rate"] == 0.1667
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
    assert summary["observed_rows"] == 0
    assert summary["classifier_runs"] == 0
    assert summary["skipped_rows"] == 0
    assert summary["skip_reasons"] == {}
    assert summary["classifier_error_rate"] == 0.0
    assert summary["gates"]["volume>=200"] is False
