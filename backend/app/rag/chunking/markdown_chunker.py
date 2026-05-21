"""Markdown text/table chunker."""

from __future__ import annotations

import html.parser
import json
import os
import re
import tiktoken
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from app.rag.ingestion.config import IngestionConfig

_enc = tiktoken.get_encoding("o200k_base")


@dataclass
class HeadingState:
    levels: dict[int, str] = field(default_factory=dict)

    def update(self, level: int, title: str):
        self.levels[level] = title.strip()
        for key in list(self.levels):
            if key > level:
                del self.levels[key]

    @property
    def title(self) -> str:
        return self.levels.get(max(self.levels), "") if self.levels else ""

    @property
    def parent_title(self) -> str:
        if len(self.levels) < 2:
            return ""
        keys = sorted(self.levels)
        return self.levels.get(keys[-2], "")

    @property
    def section_title(self) -> str:
        return " > ".join(v for _, v in sorted(self.levels.items()) if v)


def split_markdown_document(
    markdown: str,
    *,
    document_id: str,
    filename: str,
    source_path: str,
    parsed_dir: str,
    entity_name: str = "",
    cfg: IngestionConfig | None = None,
) -> tuple[list[dict], int]:
    """Split Markdown into text and table chunks."""
    cfg = cfg or IngestionConfig()
    tables_dir = os.path.join(parsed_dir, "tables")
    os.makedirs(tables_dir, exist_ok=True)

    chunks: list[dict] = []
    heading = HeadingState()
    text_lines: list[str] = []
    table_index = 0

    lines = markdown.splitlines()
    i = 0

    def flush_text():
        nonlocal text_lines
        text = "\n".join(text_lines).strip()
        text_lines = []
        if not text:
            return
        for part, chunk_text in enumerate(_split_text(text, cfg), start=1):
            chunks.append(_base_chunk(
                content=chunk_text,
                document_id=document_id,
                filename=filename,
                source_path=source_path,
                heading=heading,
                part=part,
                source_type="text",
                entity_name=entity_name,
            ))

    while i < len(lines):
        line = lines[i]
        heading_match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading_match:
            flush_text()
            heading.update(len(heading_match.group(1)), heading_match.group(2))
            text_lines.append(line)
            i += 1
            continue

        if _is_html_table_start(line):
            table_lines, i = _collect_html_table(lines, i)
            table_index += 1
            chunks.extend(_build_table_chunks(
                raw_table="\n".join(table_lines),
                table_format="html",
                table_index=table_index,
                document_id=document_id,
                filename=filename,
                source_path=source_path,
                parsed_dir=parsed_dir,
                tables_dir=tables_dir,
                heading=heading,
                entity_name=entity_name,
                cfg=cfg,
            ))
            text_lines.append(f"[表格: {_table_title(heading)}, table_id={_table_id(document_id, table_index)}]")
            continue

        if _is_markdown_table_start(lines, i):
            table_lines, i = _collect_markdown_table(lines, i)
            table_index += 1
            chunks.extend(_build_table_chunks(
                raw_table="\n".join(table_lines),
                table_format="md",
                table_index=table_index,
                document_id=document_id,
                filename=filename,
                source_path=source_path,
                parsed_dir=parsed_dir,
                tables_dir=tables_dir,
                heading=heading,
                entity_name=entity_name,
                cfg=cfg,
            ))
            text_lines.append(f"[表格: {_table_title(heading)}, table_id={_table_id(document_id, table_index)}]")
            continue

        text_lines.append(line)
        i += 1

    flush_text()

    chunks_path = os.path.join(parsed_dir, "chunks.json")
    Path(chunks_path).write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    return chunks, table_index


def _base_chunk(
    *,
    content: str,
    document_id: str,
    filename: str,
    source_path: str,
    heading: HeadingState,
    part: int,
    source_type: str,
    table_id: str = "",
    table_title: str = "",
    raw_table_path: str = "",
    table_tokens: int = 0,
    entity_name: str = "",
) -> dict:
    return {
        "content": content,
        "title": heading.title,
        "parent_title": heading.parent_title,
        "section_title": heading.section_title,
        "part": part,
        "file_title": filename,
        "source": source_path,
        "document_id": document_id,
        "page": None,
        "source_type": source_type,
        "table_id": table_id,
        "table_title": table_title,
        "raw_table_path": raw_table_path,
        "table_tokens": table_tokens,
        "entity_name": entity_name,
        "image_paths": [],
    }


def _build_table_chunks(
    *,
    raw_table: str,
    table_format: str,
    table_index: int,
    document_id: str,
    filename: str,
    source_path: str,
    parsed_dir: str,
    tables_dir: str,
    heading: HeadingState,
    entity_name: str = "",
    cfg: IngestionConfig | None = None,
) -> list[dict]:
    cfg = cfg or IngestionConfig()
    table_id = _table_id(document_id, table_index)
    table_title = _table_title(heading)
    raw_table_path = os.path.join(tables_dir, f"{table_id}.{table_format}")
    Path(raw_table_path).write_text(raw_table, encoding="utf-8")

    rows = _table_rows(raw_table, table_format)
    data_rows = _data_row_count(rows)
    column_count = max((len(row) for row in rows), default=0)
    table_tokens = _count_tokens(raw_table)
    column_names = ", ".join(rows[0]) if rows else ""

    summary = "\n".join([
        "表格摘要",
        f"表格ID: {table_id}",
        f"表格标题: {table_title}",
        f"章节路径: {heading.section_title}",
        "页码: ",
        f"规模: {data_rows} 行 x {column_count} 列，约 {table_tokens} tokens",
        f"列名: {column_names}",
        f"原始表格路径: {raw_table_path}",
    ])

    result = [
        _base_chunk(
            content=summary,
            document_id=document_id,
            filename=filename,
            source_path=source_path,
            heading=heading,
            part=1,
            source_type="table_summary",
            table_id=table_id,
            table_title=table_title,
            raw_table_path=raw_table_path,
            table_tokens=table_tokens,
            entity_name=entity_name,
        )
    ]

    if table_tokens <= cfg.table_full_token_limit:
        content = "\n".join([
            f"表格标题: {table_title}",
            f"章节路径: {heading.section_title}",
            f"原始表格路径: {raw_table_path}",
            "",
            raw_table,
        ])
        result.append(_base_chunk(
            content=content,
            document_id=document_id,
            filename=filename,
            source_path=source_path,
            heading=heading,
            part=1,
            source_type="table_full",
            table_id=table_id,
            table_title=table_title,
            raw_table_path=raw_table_path,
            table_tokens=table_tokens,
            entity_name=entity_name,
        ))
    else:
        result.extend(_table_row_groups(
            rows=rows,
            raw_table=raw_table,
            table_id=table_id,
            table_title=table_title,
            raw_table_path=raw_table_path,
            document_id=document_id,
            filename=filename,
            source_path=source_path,
            heading=heading,
            table_tokens=table_tokens,
            entity_name=entity_name,
            cfg=cfg,
        ))

    return result


def _table_row_groups(
    *,
    rows: list[list[str]],
    raw_table: str,
    table_id: str,
    table_title: str,
    raw_table_path: str,
    document_id: str,
    filename: str,
    source_path: str,
    heading: HeadingState,
    table_tokens: int = 0,
    entity_name: str = "",
    cfg: IngestionConfig | None = None,
) -> list[dict]:
    cfg = cfg or IngestionConfig()
    if not rows:
        rows = [[line] for line in raw_table.splitlines() if line.strip()]

    header = rows[0]
    data = rows[1:] if len(rows) > 1 else rows
    groups = []
    current: list[list[str]] = []
    start_row = 1

    def emit(end_row: int):
        nonlocal current, start_row
        if not current:
            return
        markdown_rows = _rows_to_markdown([header] + current)
        content = "\n".join([
            "表格行组",
            f"表格ID: {table_id}",
            f"表格标题: {table_title}",
            f"章节路径: {heading.section_title}",
            "页码: ",
            f"列名: {', '.join(header)}",
            f"行范围: {start_row}-{end_row}",
            f"原始表格路径: {raw_table_path}",
            "",
            markdown_rows,
        ])
        groups.append(_base_chunk(
            content=content,
            document_id=document_id,
            filename=filename,
            source_path=source_path,
            heading=heading,
            part=len(groups) + 1,
            source_type="table_row_group",
            table_id=table_id,
            table_title=table_title,
            raw_table_path=raw_table_path,
            table_tokens=table_tokens,
            entity_name=entity_name,
        ))
        current = []
        start_row = end_row + 1

    for idx, row in enumerate(data, start=1):
        candidate = current + [row]
        candidate_tokens = _count_tokens(_rows_to_markdown([header] + candidate))
        if current and (
            len(candidate) > cfg.table_group_max_rows or candidate_tokens > cfg.table_group_hard_tokens
        ):
            emit(idx - 1)
        current.append(row)

    emit(len(data))
    return groups


def _split_text(text: str, cfg: IngestionConfig | None = None) -> Iterable[str]:
    cfg = cfg or IngestionConfig()
    text = text.strip()
    if len(text) <= cfg.text_chunk_size:
        yield text
        return
    start = 0
    while start < len(text):
        end = min(len(text), start + cfg.text_chunk_size)
        yield text[start:end].strip()
        if end >= len(text):
            break
        start = max(0, end - cfg.text_chunk_overlap)


def _is_markdown_table_start(lines: list[str], idx: int) -> bool:
    if idx + 1 >= len(lines):
        return False
    return "|" in lines[idx] and bool(re.match(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", lines[idx + 1]))


def _collect_markdown_table(lines: list[str], idx: int) -> tuple[list[str], int]:
    collected = []
    while idx < len(lines) and "|" in lines[idx].strip() and lines[idx].strip():
        collected.append(lines[idx])
        idx += 1
    return collected, idx


def _is_html_table_start(line: str) -> bool:
    return "<table" in line.lower()


def _collect_html_table(lines: list[str], idx: int) -> tuple[list[str], int]:
    collected = []
    while idx < len(lines):
        collected.append(lines[idx])
        if "</table>" in lines[idx].lower():
            idx += 1
            break
        idx += 1
    return collected, idx


def _table_id(document_id: str, table_index: int) -> str:
    return f"{document_id}_t_{table_index:04d}"


def _table_title(heading: HeadingState) -> str:
    return heading.title or "未识别表格标题"


def _count_tokens(text: str) -> int:
    return len(_enc.encode(text))


def _data_row_count(rows: list[list[str]]) -> int:
    if not rows:
        return 0
    return max(0, len(rows) - 1)


def _table_rows(raw_table: str, table_format: str) -> list[list[str]]:
    if table_format == "html":
        return _html_table_rows(raw_table)
    return _markdown_table_rows(raw_table)


def _markdown_table_rows(raw_table: str) -> list[list[str]]:
    rows = []
    for line in raw_table.splitlines():
        stripped = line.strip()
        if not stripped or "|" not in stripped:
            continue
        if re.match(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$", stripped):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        rows.append(cells)
    return rows


class _HTMLTableParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "tr":
            self._row = []
        elif tag.lower() in {"td", "th"} and self._row is not None:
            self._cell = []
            self._in_cell = True

    def handle_data(self, data):
        if self._in_cell and self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag.lower() in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
            self._in_cell = False
        elif tag.lower() == "tr" and self._row is not None:
            if any(cell.strip() for cell in self._row):
                self.rows.append(self._row)
            self._row = None


def _html_table_rows(raw_table: str) -> list[list[str]]:
    parser = _HTMLTableParser()
    parser.feed(raw_table)
    return parser.rows


def _rows_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    max_cols = max(len(row) for row in rows)
    padded = [row + [""] * (max_cols - len(row)) for row in rows]
    header = padded[0]
    body = padded[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * max_cols) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)
