"""Unit tests for validate_citations."""

from app.rag.query.validate_citations import validate_citations_node


class TestValidateCitations:
    def test_extracts_valid_citations(self):
        state = {
            "answer": "Gross margin is 52% [C1], revenue is 100M [C2].",
            "context_map": {
                "C1": {"document_id": "d1", "file_title": "annual.pdf", "section_title": "finance", "source_type": "text"},
                "C2": {"document_id": "d2", "file_title": "quarter.pdf", "section_title": "revenue", "source_type": "text"},
            },
        }
        result = validate_citations_node(state)
        assert {c["id"] for c in result["citations"]} == {"C1", "C2"}

    def test_drops_unknown_ids(self):
        state = {
            "answer": "Source [C1] and [C99].",
            "context_map": {
                "C1": {"document_id": "d1", "file_title": "annual.pdf", "section_title": "", "source_type": "text"},
            },
        }
        result = validate_citations_node(state)
        ids = {c["id"] for c in result["citations"]}
        assert "C1" in ids
        assert "C99" not in ids

    def test_no_citations_in_answer(self):
        state = {
            "answer": "Answer without citations.",
            "context_map": {"C1": {"document_id": "d1", "file_title": "annual.pdf"}},
        }
        result = validate_citations_node(state)
        assert result["citations"] == []

    def test_empty_context_map(self):
        state = {
            "answer": "Mentions [C1] but context_map is empty.",
            "context_map": {},
        }
        result = validate_citations_node(state)
        assert result["citations"] == []

    def test_citation_inherits_metadata(self):
        state = {
            "answer": "See [C1].",
            "context_map": {
                "C1": {
                    "document_id": "doc-001",
                    "file_title": "annual.pdf",
                    "section_title": "finance",
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

    def test_extracts_full_width_citation_brackets(self):
        state = {
            "answer": "Answer uses full-width brackets \u3010C1\u3011.",
            "context_map": {"C1": {"document_id": "d1", "file_title": "doc.pdf"}},
        }
        result = validate_citations_node(state)
        assert [c["id"] for c in result["citations"]] == ["C1"]

    def test_extracts_spaced_and_lowercase_citations(self):
        state = {
            "answer": "Answer cites [ C2 ] and (c1).",
            "context_map": {
                "C1": {"document_id": "d1", "file_title": "doc1.pdf"},
                "C2": {"document_id": "d2", "file_title": "doc2.pdf"},
            },
        }
        result = validate_citations_node(state)
        assert [c["id"] for c in result["citations"]] == ["C1", "C2"]

    def test_extracts_compound_citations(self):
        state = {
            "answer": "Multiple sources [C1/C6], [C2, C3] and [C4、C7].",
            "context_map": {
                f"C{i}": {"document_id": f"d{i}", "file_title": f"doc{i}.md"}
                for i in range(1, 8)
            },
        }
        result = validate_citations_node(state)
        assert [c["id"] for c in result["citations"]] == [
            "C1",
            "C2",
            "C3",
            "C4",
            "C6",
            "C7",
        ]

    def test_citation_preserves_chunk_id_and_page(self):
        state = {
            "answer": "See [C1].",
            "context_map": {
                "C1": {
                    "chunk_id": 456,
                    "chunk_key": "ck_456",
                    "document_id": "doc-001",
                    "file_title": "annual.pdf",
                    "entity_name": "SMIC",
                    "section_title": "finance",
                    "page": 12,
                    "source_type": "text",
                    "table_id": "",
                    "image_paths": [],
                },
            },
        }
        result = validate_citations_node(state)
        c = result["citations"][0]
        assert c["chunk_id"] == 456
        assert c["chunk_key"] == "ck_456"
        assert c["page"] == 12
        assert c["entity_name"] == "SMIC"

    def test_discovery_falls_back_to_top_context_when_answer_has_no_citations(self):
        state = {
            "answer": "Discovery answer without inline citation markers.",
            "query_plan": {"retrieval_flavor": "discovery"},
            "context_map": {
                f"C{i}": {"document_id": f"d{i}", "file_title": f"doc-{i}.md"}
                for i in range(1, 7)
            },
        }
        result = validate_citations_node(state)
        assert [c["id"] for c in result["citations"]] == ["C1", "C2", "C3", "C4", "C5"]

    def test_discovery_keeps_explicit_citations_when_present(self):
        state = {
            "answer": "Discovery answer cites [C2].",
            "query_plan": {"retrieval_flavor": "discovery"},
            "context_map": {
                "C1": {"document_id": "d1", "file_title": "doc-1.md"},
                "C2": {"document_id": "d2", "file_title": "doc-2.md"},
            },
        }
        result = validate_citations_node(state)
        assert [c["id"] for c in result["citations"]] == ["C2"]

    def test_multi_hop_hop_plan_falls_back_to_context(self):
        state = {
            "answer": "Multi-hop answer without inline citation markers.",
            "hop_plan": "discovery",
            "context_map": {
                "C1": {"document_id": "d1", "file_title": "doc-1.md"},
            },
        }
        result = validate_citations_node(state)
        assert [c["id"] for c in result["citations"]] == ["C1"]
