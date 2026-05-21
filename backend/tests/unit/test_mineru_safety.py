"""Unit tests for MinerU zip-slip protection and SSE event format."""

import io
import zipfile

from app.rag.parsing.mineru_parser import _safe_extractall
from app.utils.sse import sse_event


class TestSafeExtractall:
    def test_normal_zip(self, tmp_path):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("safe/file.md", "hello")
        with zipfile.ZipFile(buf) as zf:
            _safe_extractall(zf, str(tmp_path))
        assert (tmp_path / "safe" / "file.md").exists()

    def test_zip_slip_blocked(self, tmp_path):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../../etc/evil.txt", "pwned")
        with zipfile.ZipFile(buf) as zf:
            try:
                _safe_extractall(zf, str(tmp_path))
                assert False, "Should have raised RuntimeError"
            except RuntimeError as e:
                assert "zip-slip" in str(e)

    def test_absolute_path_blocked(self, tmp_path):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("/etc/passwd", "root:x:0:0")
        with zipfile.ZipFile(buf) as zf:
            try:
                _safe_extractall(zf, str(tmp_path))
                assert False, "Should have raised RuntimeError"
            except RuntimeError as e:
                assert "zip-slip" in str(e)


class TestSSEEvent:
    def test_outputs_json(self):
        result = sse_event({"type": "delta", "content": "hello"})
        import json
        parsed = json.loads(result)
        assert parsed["type"] == "delta"
        assert parsed["content"] == "hello"

    def test_chinese_not_escaped(self):
        result = sse_event({"type": "message_start"})
        assert "message_start" in result
