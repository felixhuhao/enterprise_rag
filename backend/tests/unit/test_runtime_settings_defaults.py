def test_intent_flags_default_to_active():
    from app.core.runtime_settings import _DEFAULTS

    assert _DEFAULTS["intent.inline_enabled"] == "true"
    assert _DEFAULTS["intent.active_mode"] == "true"


def test_multi_hop_default_is_enabled_for_2d():
    from app.core.runtime_settings import _DEFAULTS
    from app.rag.query.config import QueryConfig

    assert QueryConfig().use_multi_hop is True
    assert _DEFAULTS["query.use_multi_hop"] == "True"
