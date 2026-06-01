from app.rag.query.filter_utils import (
    build_acl_expr,
    build_entity_expr,
    combine_filters,
    escape_milvus_string,
    get_allowed_ids,
)


def test_escape_milvus_string_escapes_quotes_and_backslashes():
    assert escape_milvus_string('ACME "HQ" \\ North') == 'ACME \\"HQ\\" \\\\ North'


def test_build_acl_expr_escapes_document_ids():
    expr = build_acl_expr(['doc"1', r"folder\doc"])

    assert expr == 'document_id in ["doc\\"1", "folder\\\\doc"]'


def test_build_entity_expr_escapes_entity_name():
    expr = build_entity_expr('ACME "HQ"')

    assert expr == 'entity_name == "ACME \\"HQ\\""'


def test_combine_filters_wraps_each_filter_and_ignores_empty_values():
    expr = combine_filters('document_id in ["doc-1"]', None, "", 'entity_name == "ACME"')

    assert expr == '(document_id in ["doc-1"]) and (entity_name == "ACME")'


def test_combine_filters_returns_none_without_filters():
    assert combine_filters(None, "") is None


def test_get_allowed_ids_distinguishes_missing_from_empty_acl():
    assert get_allowed_ids({}) is None
    assert get_allowed_ids({"configurable": {"allowed_document_ids": []}}) == []
    assert get_allowed_ids({"configurable": {"allowed_document_ids": ["doc-1"]}}) == ["doc-1"]
