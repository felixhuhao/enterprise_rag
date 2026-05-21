"""Markdown loading and normalization."""

from pathlib import Path


def read_markdown(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def normalize_markdown(markdown: str) -> str:
    """Normalize line endings and trailing whitespace."""
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    normalized = "\n".join(lines).strip() + "\n"
    return normalized


def write_markdown(path: str, markdown: str) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding="utf-8")
    return str(target)
