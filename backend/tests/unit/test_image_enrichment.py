"""Unit tests for image enrichment in markdown_chunker."""

from app.rag.chunking.markdown_chunker import (
    _enrich_images_in_text,
    split_markdown_document,
)


class TestEnrichImagesReplacesMarkdownRefs:
    def test_replaces_image_with_description(self):
        text = "## 营收趋势\n\n![](images/revenue_chart.jpg)\n\n上述图表展示了增长趋势。"
        descriptions = {
            "images/revenue_chart.jpg": {
                "description": "折线图显示2022-2024年营业收入从452亿元增长至578亿元",
                "image_path": "/path/to/images/revenue_chart.jpg",
                "status": "ok",
            }
        }
        enriched, paths = _enrich_images_in_text(text, descriptions)
        assert "[图片描述：折线图显示2022-2024年营业收入从452亿元增长至578亿元]" in enriched
        assert "![](images/revenue_chart.jpg)" not in enriched
        assert len(paths) == 1
        assert "/path/to/images/revenue_chart.jpg" in paths[0]

    def test_replaces_multiple_images(self):
        text = "图1: ![](images/a.png)\n\n图2: ![](images/b.jpg)"
        descriptions = {
            "images/a.png": {"description": "图表A描述", "image_path": "/p/a.png", "status": "ok"},
            "images/b.jpg": {"description": "图表B描述", "image_path": "/p/b.jpg", "status": "ok"},
        }
        enriched, paths = _enrich_images_in_text(text, descriptions)
        assert "[图片描述：图表A描述]" in enriched
        assert "[图片描述：图表B描述]" in enriched
        assert len(paths) == 2

    def test_handles_alt_text(self):
        text = "![营收图表](images/chart.jpg)"
        descriptions = {
            "images/chart.jpg": {"description": "营收数据", "image_path": "/p/chart.jpg", "status": "ok"},
        }
        enriched, paths = _enrich_images_in_text(text, descriptions)
        assert "[图片描述：营收数据]" in enriched
        assert len(paths) == 1


class TestEnrichImagesKeepsOriginalWhenMissing:
    def test_keeps_ref_when_no_description(self):
        text = "![](images/unknown.jpg)\n一些文本"
        descriptions = {}
        enriched, paths = _enrich_images_in_text(text, descriptions)
        assert "![](images/unknown.jpg)" in enriched
        assert paths == ["images/unknown.jpg"]

    def test_keeps_ref_when_status_failed(self):
        text = "![](images/broken.png)"
        descriptions = {
            "images/broken.png": {"description": None, "status": "failed", "error": "timeout"},
        }
        enriched, paths = _enrich_images_in_text(text, descriptions)
        assert "![](images/broken.png)" in enriched
        assert paths == ["images/broken.png"]

    def test_empty_descriptions_returns_unchanged(self):
        text = "![](images/foo.jpg)"
        enriched, paths = _enrich_images_in_text(text, {})
        assert enriched == text
        assert paths == ["images/foo.jpg"]


class TestFallbackBasenameMatching:
    def test_basename_fallback(self):
        text = "![](foo.jpg)"
        descriptions = {
            "images/foo.jpg": {"description": "foo描述", "image_path": "/p/foo.jpg", "status": "ok"},
        }
        enriched, paths = _enrich_images_in_text(text, descriptions)
        assert "[图片描述：foo描述]" in enriched
        assert len(paths) == 1

    def test_strips_dot_slash_prefix(self):
        text = "![](./images/chart.png)"
        descriptions = {
            "images/chart.png": {"description": "chart描述", "image_path": "/p/chart.png", "status": "ok"},
        }
        enriched, paths = _enrich_images_in_text(text, descriptions)
        assert "[图片描述：chart描述]" in enriched
        assert len(paths) == 1

    def test_full_path_takes_priority_over_basename(self):
        text = "![](images/a.jpg)"
        descriptions = {
            "images/a.jpg": {"description": "正确描述", "image_path": "/p/a.jpg", "status": "ok"},
            "other/a.jpg": {"description": "错误描述", "image_path": "/q/a.jpg", "status": "ok"},
        }
        enriched, paths = _enrich_images_in_text(text, descriptions)
        assert "正确描述" in enriched
        assert "错误描述" not in enriched


class TestReturnsImagePaths:
    def test_image_paths_collected(self):
        text = "![](images/x.png)\n![](images/y.jpg)"
        descriptions = {
            "images/x.png": {"description": "X图", "image_path": "/abs/x.png", "status": "ok"},
            "images/y.jpg": {"description": "Y图", "image_path": "/abs/y.jpg", "status": "ok"},
        }
        _, paths = _enrich_images_in_text(text, descriptions)
        assert paths == ["/abs/x.png", "/abs/y.jpg"]

    def test_image_paths_are_deduplicated(self):
        text = "![](images/x.png)\n![](images/x.png)"
        _, paths = _enrich_images_in_text(text, {})
        assert paths == ["images/x.png"]


class TestSplitWithImageDescriptions:
    def test_text_chunks_get_image_paths(self, tmp_parsed_dir):
        md = "# 标题\n\n![](images/chart.jpg)\n\n说明文字\n"
        descriptions = {
            "images/chart.jpg": {"description": "营收趋势图", "image_path": "/p/chart.jpg", "status": "ok"},
        }
        chunks, _ = split_markdown_document(
            md,
            document_id="test",
            filename="test.md",
            source_path="/tmp/test.md",
            parsed_dir=tmp_parsed_dir,
            image_descriptions=descriptions,
        )
        text_chunks = [c for c in chunks if c["source_type"] == "text"]
        # At least one text chunk should have image_paths
        with_images = [c for c in text_chunks if c["image_paths"]]
        assert len(with_images) >= 1
        assert "/p/chart.jpg" in with_images[0]["image_paths"]

    def test_text_chunks_keep_image_paths_without_descriptions(self, tmp_parsed_dir):
        md = "# 标题\n\n![](images/chart.jpg)\n\n说明文字\n"
        chunks, _ = split_markdown_document(
            md,
            document_id="test",
            filename="test.md",
            source_path="/tmp/test.md",
            parsed_dir=tmp_parsed_dir,
            image_descriptions={},
        )
        text_chunks = [c for c in chunks if c["source_type"] == "text"]
        with_images = [c for c in text_chunks if c["image_paths"]]
        assert len(with_images) >= 1
        assert with_images[0]["image_paths"] == ["images/chart.jpg"]
        assert "![](images/chart.jpg)" in with_images[0]["content"]

    def test_table_chunks_have_empty_image_paths(self, tmp_parsed_dir):
        md = "## 表\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
        chunks, _ = split_markdown_document(
            md,
            document_id="test",
            filename="test.md",
            source_path="/tmp/test.md",
            parsed_dir=tmp_parsed_dir,
        )
        table_chunks = [c for c in chunks if c["source_type"].startswith("table")]
        for c in table_chunks:
            assert c["image_paths"] == []
