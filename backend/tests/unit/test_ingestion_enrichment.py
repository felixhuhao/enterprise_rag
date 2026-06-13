import json
import sys
import types

from app.rag.ingestion.config import IngestionConfig
from app.rag.ingestion import graph
from app.rag.ingestion.graph import chunk, enrich_search_metadata, run_ingestion_graph


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_chunk_node_always_persists_chunks_artifact(tmp_path):
    state = {
        "document_id": "doc-1",
        "filename": "policy.md",
        "source_path": "/tmp/policy.md",
        "parsed_dir": str(tmp_path),
        "entity_name": "星辰科技",
        "markdown": "# API 网关\n\n星辰科技 API 网关配置说明，包含调用上限、认证策略、告警规则和审计要求。",
    }

    result = chunk(state, {"configurable": {}})

    chunks_json = _read_json(tmp_path / "chunks.json")
    assert result["chunks"]
    assert chunks_json[0]["content"] == result["chunks"][0]["content"]


def test_enrich_search_metadata_defaults_to_plain_chunks(tmp_path):
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
    assert "search_text" not in enriched
    assert "structured_tags" not in enriched
    assert "keywords" not in enriched

    chunks_json = _read_json(tmp_path / "chunks.json")
    quality_json = _read_json(tmp_path / "chunk_quality.json")
    history_json = _read_json(tmp_path / "processing_history.json")

    assert chunks_json == [chunk]
    assert quality_json["document_id"] == "doc-1"
    assert quality_json["chunk_count"] == 1
    assert quality_json["enrichment_profile"] == "none"
    assert result["quality_report"] == quality_json
    assert history_json[-1]["chunk_count"] == 1
    assert history_json[-1]["enrichment_profile"] == "none"
    assert history_json[-1]["quality_status"] == quality_json["status"]
    assert not (tmp_path / "chunk_enrichment.json").exists()


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
    chunks_json = _read_json(tmp_path / "chunks.json")
    quality_json = _read_json(tmp_path / "chunk_quality.json")
    history_json = _read_json(tmp_path / "processing_history.json")

    assert chunks_json == [chunk]
    assert quality_json["enrichment_profile"] == "none"
    assert result["quality_report"] == quality_json
    assert history_json[-1]["enrichment_profile"] == "none"
    assert not (tmp_path / "chunk_enrichment.json").exists()


def test_enrich_search_metadata_resets_malformed_processing_history(tmp_path):
    (tmp_path / "processing_history.json").write_text("{bad json", encoding="utf-8")
    chunk = {
        "content": "星辰科技 API 网关配置说明，包含调用上限、认证策略、告警规则、审计要求和异常处理流程。",
        "metadata": {"chunk_id": "c1"},
        "section_title": "API 网关",
        "source_type": "text",
    }
    state = {
        "document_id": "doc-1",
        "parsed_dir": str(tmp_path),
        "chunks": [chunk],
        "file_type": "md",
    }

    enrich_search_metadata(
        state,
        {"configurable": {"ingestion_config": IngestionConfig(chunk_enrichment_enabled=False)}},
    )

    history_json = _read_json(tmp_path / "processing_history.json")
    assert isinstance(history_json, list)
    assert history_json[-1]["chunk_count"] == 1


def test_run_ingestion_graph_returns_quality_summary(tmp_path, monkeypatch):
    source = tmp_path / "policy.md"
    source.write_text(
        "# API 网关\n\n"
        "星辰科技 API 网关配置说明，包含调用上限、认证策略、告警规则、审计要求、异常处理和升级路径。",
        encoding="utf-8",
    )
    parsed_root = tmp_path / "parsed"
    monkeypatch.setattr(graph.settings, "GENERAL_PARSED_DIR", str(parsed_root))

    dense_module = types.ModuleType("app.rag.embeddings.dense_embedding")
    dense_module.embed_chunks = lambda chunks: chunks
    milvus_module = types.ModuleType("app.rag.vectorstores.general_milvus")
    milvus_module.upsert_document_chunks = lambda document_id, chunks: None
    monkeypatch.setitem(sys.modules, "app.rag.embeddings.dense_embedding", dense_module)
    monkeypatch.setitem(sys.modules, "app.rag.vectorstores.general_milvus", milvus_module)

    result = run_ingestion_graph({
        "document_id": "doc-graph",
        "filename": "policy.md",
        "file_type": "md",
        "source_path": str(source),
        "entity_name": "星辰科技",
    })

    quality_json = _read_json(parsed_root / "doc-graph" / "chunk_quality.json")
    history_json = _read_json(parsed_root / "doc-graph" / "processing_history.json")

    assert result["chunk_count"] == quality_json["chunk_count"]
    assert result["quality_status"] == quality_json["status"]
    assert result["quality_warning_count"] == sum(row["count"] for row in quality_json["warnings"])
    assert result["parser_version"] == "markdown_v1"
    assert result["chunker_version"] == "markdown_chunker_v1"
    assert history_json[-1]["quality_status"] == result["quality_status"]
