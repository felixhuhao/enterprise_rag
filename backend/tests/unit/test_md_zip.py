"""Unit tests for parse_md_zip() — Markdown zip parsing."""

import os
import shutil
import zipfile
from pathlib import Path

import pytest

from app.rag.parsing.mineru_parser import parse_md_zip


@pytest.fixture
def tmp_output(tmp_path):
    """Clean output directory for each test."""
    out = tmp_path / "parsed"
    out.mkdir()
    return str(out)


def _make_zip(tmp_path, files: dict[str, str], name: str = "test.zip") -> str:
    """Create a zip file with given {relative_path: content} entries."""
    zip_path = tmp_path / name
    with zipfile.ZipFile(str(zip_path), "w") as zf:
        for rel, content in files.items():
            zf.writestr(rel, content)
    return str(zip_path)


def _make_zip_with_bin(tmp_path, files: dict[str, str], bin_files: dict[str, bytes], name: str = "test.zip") -> str:
    """Create a zip with text and binary entries."""
    zip_path = tmp_path / name
    with zipfile.ZipFile(str(zip_path), "w") as zf:
        for rel, content in files.items():
            zf.writestr(rel, content)
        for rel, data in bin_files.items():
            zf.writestr(rel, data)
    return str(zip_path)


# ---- Normal case ----

def test_normal_zip(tmp_path, tmp_output):
    zip_path = _make_zip_with_bin(
        tmp_path,
        files={"document.md": "# Hello\n\nSome text\n\n![](images/test.png)"},
        bin_files={"images/test.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 100},
    )
    result = parse_md_zip(zip_path, tmp_output)

    assert result.markdown_content.strip().startswith("# Hello")
    assert os.path.isfile(os.path.join(tmp_output, "document.md"))
    assert os.path.isdir(os.path.join(tmp_output, "images"))
    assert os.path.isfile(os.path.join(tmp_output, "images", "test.png"))
    # zip_raw preserved for debugging
    assert os.path.isdir(os.path.join(tmp_output, "zip_raw"))


# ---- No markdown file ----

def test_no_markdown_raises(tmp_path, tmp_output):
    zip_path = _make_zip(tmp_path, {"readme.txt": "no markdown here"})
    with pytest.raises(RuntimeError, match="no markdown file"):
        parse_md_zip(zip_path, tmp_output)


# ---- Empty zip ----

def test_empty_zip_raises(tmp_path, tmp_output):
    zip_path = _make_zip(tmp_path, {})
    with pytest.raises(RuntimeError, match="no markdown file"):
        parse_md_zip(zip_path, tmp_output)


# ---- Zip slip ----

def test_zip_slip_raises(tmp_path, tmp_output):
    zip_path = str(tmp_path / "evil.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        # path traversal entry
        zf.writestr("../../etc/passwd", "evil")
    with pytest.raises(RuntimeError, match="zip-slip"):
        parse_md_zip(zip_path, tmp_output)


# ---- Oversized uncompressed ----

def test_oversized_zip_raises(tmp_path, tmp_output, monkeypatch):
    monkeypatch.setattr("app.rag.parsing.mineru_parser.settings.MD_ZIP_MAX_SIZE_MB", 0)
    zip_path = _make_zip(tmp_path, {"document.md": "# Hi"})
    with pytest.raises(RuntimeError, match="exceeds"):
        parse_md_zip(zip_path, tmp_output)


# ---- Too many files ----

def test_too_many_files_raises(tmp_path, tmp_output, monkeypatch):
    monkeypatch.setattr("app.rag.parsing.mineru_parser._MAX_ZIP_FILES", 2)
    files = {f"file_{i}.txt": f"content {i}" for i in range(5)}
    zip_path = _make_zip(tmp_path, files)
    with pytest.raises(RuntimeError, match="file limit"):
        parse_md_zip(zip_path, tmp_output)


# ---- Images copied to standard directory ----

def test_images_copied_to_standard_dir(tmp_path, tmp_output):
    png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    zip_path = _make_zip_with_bin(
        tmp_path,
        files={"document.md": "# Report\n\nChart below:\n\n![](images/chart.png)"},
        bin_files={"images/chart.png": png_data},
    )
    parse_md_zip(zip_path, tmp_output)

    assert os.path.isfile(os.path.join(tmp_output, "images", "chart.png"))
    with open(os.path.join(tmp_output, "images", "chart.png"), "rb") as f:
        assert f.read() == png_data


def test_parse_md_zip_does_not_require_metadata_preserving_copy(tmp_path, tmp_output, monkeypatch):
    png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    zip_path = _make_zip_with_bin(
        tmp_path,
        files={"document.md": "# Report\n\nChart below:\n\n![](images/chart.png)"},
        bin_files={"images/chart.png": png_data},
    )

    def _raise_copy_error(*args, **kwargs):
        raise PermissionError("metadata copy is not allowed")

    monkeypatch.setattr("app.rag.parsing.mineru_parser.shutil.copy2", _raise_copy_error)
    monkeypatch.setattr("app.rag.parsing.mineru_parser.shutil.copytree", _raise_copy_error)

    result = parse_md_zip(zip_path, tmp_output)

    assert "Report" in result.markdown_content
    assert os.path.isfile(os.path.join(tmp_output, "document.md"))
    assert os.path.isfile(os.path.join(tmp_output, "images", "chart.png"))
    with open(os.path.join(tmp_output, "images", "chart.png"), "rb") as f:
        assert f.read() == png_data


# ---- Root single .md fallback ----

def test_root_single_md_fallback(tmp_path, tmp_output):
    zip_path = _make_zip(tmp_path, {"report.md": "# Report\n\nContent"})
    result = parse_md_zip(zip_path, tmp_output)
    assert "Report" in result.markdown_content
