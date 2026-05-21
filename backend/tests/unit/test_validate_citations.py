"""Unit tests for validate_citations: extract [C1]/[C2], match context_map, drop hallucinations."""

from app.rag.query.validate_citations import validate_citations_node


class TestValidateCitations:
    def test_extracts_valid_citations(self):
        state = {
            "answer": "毛利率为 52% [C1]，营收为 100亿 [C2]。",
            "context_map": {
                "C1": {"document_id": "d1", "file_title": "年报.pdf", "section_title": "财务", "source_type": "text"},
                "C2": {"document_id": "d2", "file_title": "季报.pdf", "section_title": "营收", "source_type": "text"},
            },
        }
        result = validate_citations_node(state)
        citations = result["citations"]
        ids = {c["id"] for c in citations}
        assert ids == {"C1", "C2"}

    def test_drops_unknown_ids(self):
        state = {
            "answer": "数据来源 [C1] 和 [C99]。",
            "context_map": {
                "C1": {"document_id": "d1", "file_title": "年报.pdf", "section_title": "", "source_type": "text"},
            },
        }
        result = validate_citations_node(state)
        ids = {c["id"] for c in result["citations"]}
        assert "C1" in ids
        assert "C99" not in ids

    def test_no_citations_in_answer(self):
        state = {
            "answer": "没有引用的回答。",
            "context_map": {"C1": {"document_id": "d1", "file_title": "年报.pdf"}},
        }
        result = validate_citations_node(state)
        assert result["citations"] == []

    def test_empty_context_map(self):
        state = {
            "answer": "提到 [C1] 但 context_map 为空。",
            "context_map": {},
        }
        result = validate_citations_node(state)
        assert result["citations"] == []

    def test_citation_inherits_metadata(self):
        state = {
            "answer": "参考 [C1]。",
            "context_map": {
                "C1": {
                    "document_id": "doc-001",
                    "file_title": "年报.pdf",
                    "section_title": "财务数据",
                    "table_id": "doc-001_t_0001",
                    "source_type": "table_full",
                },
            },
        }
        result = validate_citations_node(state)
        c = result["citations"][0]
        assert c["document_id"] == "doc-001"
        assert c["source_type"] == "table_full"
        assert c["table_id"] == "doc-001_t_0001"
