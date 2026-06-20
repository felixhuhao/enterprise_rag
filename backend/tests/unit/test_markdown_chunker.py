"""Unit tests for markdown_chunker: text chunks, table chunks, section titles, config."""

from app.rag.chunking.markdown_chunker import split_markdown_document
from app.rag.ingestion.config import IngestionConfig


class TestTextChunks:
    def test_text_chunks_keep_section_title(self, sample_markdown, tmp_parsed_dir):
        chunks, _ = split_markdown_document(
            sample_markdown,
            document_id="test",
            filename="test.md",
            source_path="/tmp/test.md",
            parsed_dir=tmp_parsed_dir,
        )
        text_chunks = [c for c in chunks if c["source_type"] == "text"]
        # 验证 section_title 被传播
        for c in text_chunks:
            if c["content"].startswith("#"):
                continue
            assert c["section_title"] != "", f"text chunk missing section_title: {c['content'][:40]}"

    def test_text_chunk_size_respects_config(self, tmp_parsed_dir):
        long_text = "A" * 5000
        md = f"# Title\n\n{long_text}"
        cfg = IngestionConfig(text_chunk_size=500, text_chunk_overlap=50)
        chunks, _ = split_markdown_document(
            md, document_id="test", filename="test.md",
            source_path="/tmp/test.md", parsed_dir=tmp_parsed_dir, cfg=cfg,
        )
        text_chunks = [c for c in chunks if c["source_type"] == "text"]
        # 5000 / 500 = 至少 10 个 chunk
        assert len(text_chunks) >= 8

    def test_default_config_unchanged(self, sample_markdown, tmp_parsed_dir):
        chunks, _ = split_markdown_document(
            sample_markdown, document_id="test", filename="test.md",
            source_path="/tmp/test.md", parsed_dir=tmp_parsed_dir,
        )
        assert len(chunks) > 0
        # 默认 chunk_size=1200，这个 md 不长，不会有太多 text chunks
        text_chunks = [c for c in chunks if c["source_type"] == "text"]
        assert len(text_chunks) >= 2


class TestHeadingOnlyFragments:
    def test_consecutive_headings_do_not_yield_heading_only_chunks(self, tmp_parsed_dir):
        """A heading immediately followed by a subheading must not become a
        standalone text chunk containing only the heading line."""
        md = "# 文档\n\n## 第二章 差旅标准\n\n### 2.1 国内差旅\n\n差旅标准如下。\n"
        chunks, _ = split_markdown_document(
            md, document_id="test", filename="test.md",
            source_path="/tmp/test.md", parsed_dir=tmp_parsed_dir,
        )
        text_chunks = [c for c in chunks if c["source_type"] == "text"]

        def is_heading_only(content: str) -> bool:
            lines = [ln for ln in content.splitlines() if ln.strip()]
            return bool(lines) and all(ln.lstrip().startswith("#") for ln in lines)

        heading_only = [c for c in text_chunks if is_heading_only(c["content"])]
        assert not heading_only, f"heading-only chunks emitted: {[c['content'] for c in heading_only]}"

        # section context must still be preserved on the body chunk
        body = next(c for c in text_chunks if "差旅标准如下" in c["content"])
        assert "第二章 差旅标准" in body["section_title"]
        assert "2.1 国内差旅" in body["section_title"]


class TestMarkdownTable:
    def test_small_table_generates_summary_and_full(self, tmp_parsed_dir):
        md = "## 财务\n\n| 指标 | 值 |\n|------|-----|\n| 营收 | 100亿 |\n"
        chunks, table_count = split_markdown_document(
            md, document_id="test", filename="test.md",
            source_path="/tmp/test.md", parsed_dir=tmp_parsed_dir,
        )
        assert table_count == 1
        types = {c["source_type"] for c in chunks}
        assert "table_summary" in types
        assert "table_full" in types

    def test_large_table_generates_summary_and_row_groups(self, tmp_parsed_dir):
        # 需要足够大的表格触发 >2000 tokens
        header = "| 指标 | Q1 | Q2 | Q3 | Q4 | Q5 | Q6 |"
        sep = "|------|-----|-----|-----|-----|-----|-----|"
        rows = [f"| 项目{i:04d}数据内容填充 | {i*10}万 | {i*20}万 | {i*30}万 | {i*40}万 | {i*50}万 | {i*60}万 |" for i in range(200)]
        md = f"## 大表\n\n{header}\n{sep}\n" + "\n".join(rows)

        chunks, table_count = split_markdown_document(
            md, document_id="test", filename="test.md",
            source_path="/tmp/test.md", parsed_dir=tmp_parsed_dir,
        )
        assert table_count == 1
        types = {c["source_type"] for c in chunks}
        assert "table_summary" in types
        assert "table_row_group" in types
        assert "table_full" not in types  # 大表不应生成 table_full

    def test_table_has_table_id(self, tmp_parsed_dir):
        md = "## 表\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
        chunks, _ = split_markdown_document(
            md, document_id="doc1", filename="test.md",
            source_path="/tmp/test.md", parsed_dir=tmp_parsed_dir,
        )
        table_chunks = [c for c in chunks if c["source_type"].startswith("table")]
        for c in table_chunks:
            assert c["table_id"] == "doc1_t_0001"

    def test_multiple_tables_sequential_ids(self, tmp_parsed_dir):
        md = (
            "## 表1\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n"
            "## 表2\n\n| C | D |\n|---|---|\n| 3 | 4 |\n"
        )
        chunks, table_count = split_markdown_document(
            md, document_id="doc1", filename="test.md",
            source_path="/tmp/test.md", parsed_dir=tmp_parsed_dir,
        )
        assert table_count == 2
        table_chunks = [c for c in chunks if c["source_type"].startswith("table")]
        ids = {c["table_id"] for c in table_chunks}
        assert "doc1_t_0001" in ids
        assert "doc1_t_0002" in ids


class TestHTMLTable:
    def test_html_table_is_detected(self, tmp_parsed_dir):
        md = '## 表\n\n<table>\n<tr><th>A</th><th>B</th></tr>\n<tr><td>1</td><td>2</td></tr>\n</table>\n'
        chunks, table_count = split_markdown_document(
            md, document_id="test", filename="test.md",
            source_path="/tmp/test.md", parsed_dir=tmp_parsed_dir,
        )
        assert table_count == 1
        table_chunks = [c for c in chunks if c["source_type"].startswith("table")]
        assert len(table_chunks) >= 1

    def test_raw_table_path_saved(self, tmp_parsed_dir):
        md = '## 表\n\n<table>\n<tr><th>A</th><th>B</th></tr>\n<tr><td>1</td><td>2</td></tr>\n</table>\n'
        chunks, _ = split_markdown_document(
            md, document_id="test", filename="test.md",
            source_path="/tmp/test.md", parsed_dir=tmp_parsed_dir,
        )
        table_chunks = [c for c in chunks if c["source_type"].startswith("table")]
        for c in table_chunks:
            assert c["raw_table_path"], "raw_table_path should be set"

    def test_unclosed_html_table_does_not_consume_rest_of_document(self, tmp_parsed_dir):
        md = "## 表\n\n<table>\n<tr><td>1</td></tr>\n\n## 后续章节\n\n后续内容必须保留"
        chunks, table_count = split_markdown_document(
            md,
            document_id="test",
            filename="test.md",
            source_path="/tmp/test.md",
            parsed_dir=tmp_parsed_dir,
        )

        assert table_count == 1
        assert any("后续内容必须保留" in chunk["content"] for chunk in chunks)


class TestIngestionConfig:
    def test_table_full_token_limit_affects_split(self, tmp_parsed_dir):
        """调低 table_full_token_limit，让中等表格走 row_groups。"""
        header = "| A | B | C |"
        sep = "|---|---|---|"
        rows = [f"| x{i} | y{i} | z{i} |" for i in range(30)]
        md = f"## 表\n\n{header}\n{sep}\n" + "\n".join(rows)

        # 默认阈值 2000，这个表可能走 full
        chunks_default, _ = split_markdown_document(
            md, document_id="test", filename="test.md",
            source_path="/tmp/test.md", parsed_dir=tmp_parsed_dir, cfg=IngestionConfig(),
        )
        # 极低阈值 10，必然走 row_groups
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            chunks_small, _ = split_markdown_document(
                md, document_id="test2", filename="test.md",
                source_path="/tmp/test.md", parsed_dir=td,
                cfg=IngestionConfig(table_full_token_limit=10),
            )
        types_small = {c["source_type"] for c in chunks_small}
        assert "table_row_group" in types_small
