from app.rag.query.control.inferred import infer_signals


def test_entity_scope_maps_from_entity_mode():
    assert infer_signals("q", "single", []).entity_scope == "single"
    assert infer_signals("q", "multi_explicit", []).entity_scope == "multi"
    assert infer_signals("q", "broad", []).entity_scope == "broad"
    assert infer_signals("q", "none", []).entity_scope == "none"


def test_needs_synthesis_from_markers():
    assert infer_signals("A和B有什么区别？", "single", []).needs_synthesis is True
    assert infer_signals("报销标准是什么？", "single", []).needs_synthesis is False


def test_needs_multi_hop_folds_decide_multi_hop():
    assert infer_signals("哪些公司提到了报销？", "broad", []).needs_multi_hop is True
    assert infer_signals("谁负责报销审批？", "none", []).needs_multi_hop is True
    assert infer_signals("哪些公司提到了报销？", "single", []).needs_multi_hop is False
    assert infer_signals("报销标准是什么？", "none", []).needs_multi_hop is False


def test_d1_invariants():
    sig = infer_signals("哪些公司提到了报销？", "broad", [])
    assert sig.needs_discovery is True
    assert sig.requested_format is None
    assert sig.confidence == "high"


def test_confidence_ladder_v1():
    assert infer_signals("所有公司的报销标准", "broad", []).confidence == "high"
    assert infer_signals("比较甲公司的报销标准", "single", []).confidence == "high"
    assert infer_signals("报销标准是什么", "single", []).confidence == "medium"
    assert infer_signals("甲公司和乙公司的地址", "multi_explicit", []).confidence == "medium"
    assert infer_signals("比较各项制度", "none", []).confidence == "medium"
    assert infer_signals("公司情况怎么样", "none", []).confidence == "low"


def test_provenance_defaults_are_deterministic():
    sig = infer_signals("报销标准是什么", "single", [])
    assert sig.source == "deterministic"
    assert sig.fallback_used is False
