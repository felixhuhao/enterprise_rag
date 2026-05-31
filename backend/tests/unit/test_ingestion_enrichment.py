import json

from app.rag.ingestion.config import IngestionConfig
from app.rag.ingestion.graph import enrich_search_metadata


def test_enrich_search_metadata_persists_chunks_and_artifact(tmp_path):
    chunk = {
        "chunk_key": "ck_1",
        "content": "单次费用超过10,000元需VP级别审批。",
        "section_title": "年度培训计划 > 五、外部培训管理",
        "file_title": "12_年度培训计划_2026.md",
        "source_type": "text",
    }
    state = {
        "document_id": "doc-1",
        "parsed_dir": str(tmp_path),
        "chunks": [chunk],
    }

    result = enrich_search_metadata(state, {"configurable": {}})

    enriched = result["chunks"][0]
    assert enriched["content"] == chunk["content"]
    assert "search_text" in enriched
    assert "amount_threshold" in enriched["structured_tags"]
    assert "approval_rule" in enriched["structured_tags"]

    chunks_json = json.loads((tmp_path / "chunks.json").read_text(encoding="utf-8"))
    artifact_json = json.loads((tmp_path / "chunk_enrichment.json").read_text(encoding="utf-8"))

    assert chunks_json[0]["search_text"] == enriched["search_text"]
    assert artifact_json == [
        {
            "chunk_key": "ck_1",
            "enrichment_profile": "enterprise_policy",
            "keywords": enriched["keywords"],
            "structured_tags": enriched["structured_tags"],
            "search_text": enriched["search_text"],
        }
    ]


def test_enrich_search_metadata_can_be_disabled(tmp_path):
    chunk = {
        "chunk_key": "ck_1",
        "content": "单次费用超过10,000元需VP级别审批。",
        "section_title": "年度培训计划 > 五、外部培训管理",
    }
    state = {
        "document_id": "doc-1",
        "parsed_dir": str(tmp_path),
        "chunks": [chunk],
    }

    result = enrich_search_metadata(
        state,
        {"configurable": {"ingestion_config": IngestionConfig(chunk_enrichment_enabled=False)}},
    )

    assert result["chunks"] == [chunk]
    assert not (tmp_path / "chunk_enrichment.json").exists()


def test_enrich_search_metadata_supports_general_profile(tmp_path):
    chunk = {
        "chunk_key": "ck_1",
        "content": "金额超过10,000元需VP级别审批。",
        "section_title": "付款管理",
    }
    state = {
        "document_id": "doc-1",
        "parsed_dir": str(tmp_path),
        "chunks": [chunk],
    }

    result = enrich_search_metadata(
        state,
        {"configurable": {"ingestion_config": IngestionConfig(chunk_enrichment_profile="general")}},
    )

    enriched = result["chunks"][0]
    assert enriched["enrichment_profile"] == "general"
    assert enriched["structured_tags"] == []
    assert "金额审批阈值" not in enriched["search_text"]
