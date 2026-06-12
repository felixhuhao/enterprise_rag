from app.rag.query.control.breadth import BREADTH_PROFILES, VALID_BREADTHS, resolve_breadth


def test_resolve_renames_legacy_flavors_1to1():
    assert resolve_breadth("exact") == "precise"
    assert resolve_breadth("balanced") == "balanced"
    assert resolve_breadth("recall") == "broad"
    assert resolve_breadth("discovery") == "discovery"


def test_resolve_passthrough_and_default():
    assert resolve_breadth("precise") == "precise"
    assert resolve_breadth("nonsense") == "balanced"


def test_profiles_match_design_3_2():
    assert VALID_BREADTHS == {"precise", "balanced", "broad", "discovery"}
    p = BREADTH_PROFILES
    assert (
        p["precise"].sets_hyde,
        p["precise"].sets_expansion,
        p["precise"].allows_fallback,
        p["precise"].permits_multi_hop,
    ) == (False, False, False, False)
    assert (
        p["balanced"].sets_hyde,
        p["balanced"].sets_expansion,
        p["balanced"].allows_fallback,
        p["balanced"].permits_multi_hop,
    ) == (True, False, True, True)
    assert (
        p["broad"].sets_hyde,
        p["broad"].sets_expansion,
        p["broad"].allows_fallback,
        p["broad"].permits_multi_hop,
    ) == (False, True, True, True)
    assert (
        p["discovery"].sets_hyde,
        p["discovery"].sets_expansion,
        p["discovery"].allows_fallback,
        p["discovery"].permits_multi_hop,
    ) == (False, False, False, True)

