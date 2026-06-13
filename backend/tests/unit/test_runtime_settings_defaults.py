def test_intent_flags_default_to_active():
    from app.core.runtime_settings import _DEFAULTS

    assert _DEFAULTS["intent.inline_enabled"] == "true"
    assert _DEFAULTS["intent.active_mode"] == "true"
