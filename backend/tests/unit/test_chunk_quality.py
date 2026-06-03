"""Unit tests for deterministic chunk quality reports."""

from app.rag.ingestion.chunk_quality import (
    DUPLICATE_CHUNK,
    EMPTY_CHUNK,
    IMAGE_WITHOUT_ASSET_PATH,
    IMAGE_WITHOUT_DESCRIPTION,
    LOW_INFORMATION_CHUNK,
    MISSING_SECTION_TITLE,
    OVERSIZED_CHUNK,
    TABLE_WITHOUT_METADATA,
    UNDERSIZED_CHUNK,
    build_chunk_quality_report,
    quality_summary,
    unavailable_quality_report,
)


def _chunk(**overrides):
    row = {
        "chunk_key": "chunk-1",
        "content": (
            "星辰科技 API 网关配置说明，包含调用上限、认证策略、告警规则、"
            "审计要求、异常处理、供应商接入审批、日志保留周期和负责人升级路径。"
            "这些内容用于确认正常制度切片不会被质量分析器误报。"
        ),
        "section_title": "API 网关",
        "source_type": "text",
        "image_paths": [],
    }
    row.update(overrides)
    return row


def _report(chunks):
    return build_chunk_quality_report(
        chunks,
        document_id="doc-1",
        parser_version="parser-test",
        chunker_version="chunker-test",
        enrichment_profile="enterprise_policy",
        processed_at="2026-06-03T10:00:00",
        source_file_type="md",
    )


def _chunk_warnings(report, index=0):
    return report["chunks"][index]["warnings"]


def _warning_counts(report):
    return {row["type"]: row["count"] for row in report["warnings"]}


def test_good_chunks_produce_good_report():
    report = _report([
        _chunk(chunk_key="a"),
        _chunk(
            chunk_key="b",
            content=(
                "远景能源的供应商审计流程覆盖准入、年度复审、整改跟踪和风险升级。"
                "安全负责人需要保留审计证据，采购团队需要在合同续签前完成复核。"
                "该段内容足够长，代表正常企业制度切片。"
            ),
        ),
    ])

    assert report["status"] == "good"
    assert report["chunk_count"] == 2
    assert report["warnings"] == []
    assert report["metrics"]["min_chunk_chars"] > 0
    assert report["parser_version"] == "parser-test"
    assert report["chunker_version"] == "chunker-test"
    assert report["enrichment_profile"] == "enterprise_policy"


def test_empty_and_low_information_chunks_are_flagged():
    report = _report([
        _chunk(chunk_key="empty", content="   "),
        _chunk(chunk_key="low", content="--- === !!!", section_title="Markers"),
    ])

    assert report["status"] == "warning"
    assert EMPTY_CHUNK in _chunk_warnings(report, 0)
    assert LOW_INFORMATION_CHUNK in _chunk_warnings(report, 1)
    counts = _warning_counts(report)
    assert counts[EMPTY_CHUNK] == 1
    assert counts[LOW_INFORMATION_CHUNK] == 1


def test_missing_section_and_size_warnings_are_flagged():
    report = _report([
        _chunk(chunk_key="missing", section_title="", title=""),
        _chunk(chunk_key="short", content="短内容", section_title="短节"),
        _chunk(chunk_key="long", content="A" * 2501, section_title="长节"),
    ])

    assert MISSING_SECTION_TITLE in _chunk_warnings(report, 0)
    assert UNDERSIZED_CHUNK in _chunk_warnings(report, 1)
    assert OVERSIZED_CHUNK in _chunk_warnings(report, 2)
    counts = _warning_counts(report)
    assert counts[MISSING_SECTION_TITLE] == 1
    assert counts[UNDERSIZED_CHUNK] == 1
    assert counts[OVERSIZED_CHUNK] == 1


def test_duplicate_chunks_are_flagged_on_each_duplicate_member():
    duplicated = "同一段制度说明会被重复切片，同一段制度说明会被重复切片。"
    report = _report([
        _chunk(chunk_key="a", content=duplicated),
        _chunk(chunk_key="b", content="  " + duplicated + "\n"),
        _chunk(chunk_key="c", content="不同内容用于确认不会误报重复。"),
    ])

    assert DUPLICATE_CHUNK in _chunk_warnings(report, 0)
    assert DUPLICATE_CHUNK in _chunk_warnings(report, 1)
    assert DUPLICATE_CHUNK not in _chunk_warnings(report, 2)
    assert _warning_counts(report)[DUPLICATE_CHUNK] == 2


def test_table_chunk_requires_stable_table_locator():
    report = _report([
        _chunk(chunk_key="bad-table", source_type="table_full", table_id="", table_title="", raw_table_path=""),
        _chunk(chunk_key="good-table", source_type="table_row_group", table_id="t-1"),
    ])

    assert TABLE_WITHOUT_METADATA in _chunk_warnings(report, 0)
    assert TABLE_WITHOUT_METADATA not in _chunk_warnings(report, 1)
    assert _warning_counts(report)[TABLE_WITHOUT_METADATA] == 1


def test_image_chunk_requires_description_and_relative_asset_paths():
    report = _report([
        _chunk(chunk_key="no-desc", image_paths=["images/a.png"]),
        _chunk(
            chunk_key="bad-path",
            content=(
                "图片描述: 系统架构图展示 API 网关、认证服务、审计服务、"
                "日志系统和告警中心之间的数据流向，并说明异常请求如何升级处理。"
            ),
            image_paths=["/tmp/a.png", "../secret.png", ""],
        ),
        _chunk(
            chunk_key="good-image",
            content=(
                "图片描述: 页面截图展示审批流程，包括申请人、直属经理、"
                "安全负责人和采购负责人四个审批节点，以及每个节点的处理时限。"
                "截图还展示了审批记录、退回原因、通知方式和最终归档状态。"
            ),
            image_paths=["images/flow.png"],
        ),
    ])

    assert IMAGE_WITHOUT_DESCRIPTION in _chunk_warnings(report, 0)
    assert IMAGE_WITHOUT_ASSET_PATH not in _chunk_warnings(report, 0)
    assert IMAGE_WITHOUT_ASSET_PATH in _chunk_warnings(report, 1)
    assert IMAGE_WITHOUT_DESCRIPTION not in _chunk_warnings(report, 1)
    assert not _chunk_warnings(report, 2)
    counts = _warning_counts(report)
    assert counts[IMAGE_WITHOUT_DESCRIPTION] == 1
    assert counts[IMAGE_WITHOUT_ASSET_PATH] == 1


def test_quality_summary_and_unavailable_report_shape():
    unavailable = unavailable_quality_report()
    assert unavailable == {
        "status": "unavailable",
        "quality_version": "",
        "metrics": {},
        "warnings": [],
        "chunks": [],
    }

    report = _report([_chunk(chunk_key="empty", content="", section_title="", source_type="table_full")])
    summary = quality_summary(report)

    assert summary == {
        "quality_status": "warning",
        "quality_warning_count": 3,
        "parser_version": "parser-test",
        "chunker_version": "chunker-test",
        "enrichment_profile": "enterprise_policy",
        "processed_at": "2026-06-03T10:00:00",
    }
