from app.rag.query.llm_json import parse_llm_json, parse_llm_json_object


def test_parse_llm_json_direct_object():
    assert parse_llm_json('{"ok":true}') == {"ok": True}


def test_parse_llm_json_fenced_object():
    raw = '```json\n{"ok":true}\n```'
    assert parse_llm_json_object(raw) == {"ok": True}


def test_parse_llm_json_strips_surrounding_text():
    raw = 'Here is the JSON:\n{"ok":true}\nThanks'
    assert parse_llm_json_object(raw) == {"ok": True}


def test_parse_llm_json_object_rejects_array():
    assert parse_llm_json("[]") == []
    assert parse_llm_json_object("[]") is None


def test_parse_llm_json_invalid_returns_none():
    assert parse_llm_json_object("not json") is None
