"""Disk-backed LLM judge cache for golden-set evaluation."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


JUDGE_CACHE_SCHEMA_VERSION = 1
JUDGE_RUBRIC_VERSION = "judge_v1"


def default_judge_cache_path() -> Path:
    backend_dir = Path(__file__).resolve().parents[2]
    data_dir = backend_dir / "data"
    if not data_dir.is_dir():
        data_dir = backend_dir.parent / "data"
    return data_dir / "eval_judge_cache.json"


def get_cached_judge_result(
    row: dict,
    chat_model: str,
    cache_path: str | Path | None = None,
    rubric_version: str = JUDGE_RUBRIC_VERSION,
) -> dict | None:
    cache = _load_cache(cache_path)
    key_hash, _payload = _cache_key(row, chat_model, rubric_version)
    entry = cache.get("entries", {}).get(key_hash)
    if not isinstance(entry, dict):
        return None
    judge = entry.get("judge")
    return copy.deepcopy(judge) if isinstance(judge, dict) else None


def put_judge_result(
    row: dict,
    chat_model: str,
    judge_result: dict,
    cache_path: str | Path | None = None,
    rubric_version: str = JUDGE_RUBRIC_VERSION,
) -> None:
    if not isinstance(judge_result, dict) or judge_result.get("error"):
        return

    cache = _load_cache(cache_path)
    key_hash, payload = _cache_key(row, chat_model, rubric_version)
    cache.setdefault("entries", {})[key_hash] = {
        "schema_version": JUDGE_CACHE_SCHEMA_VERSION,
        "key": payload,
        "judge": _json_safe(judge_result),
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_cache(cache, cache_path)


def _cache_key(row: dict, chat_model: str, rubric_version: str) -> tuple[str, dict]:
    payload = {
        "schema_version": JUDGE_CACHE_SCHEMA_VERSION,
        "rubric_version": rubric_version,
        "case_id": _normalize_text(row.get("id")),
        "question": _normalize_text(row.get("question")),
        "normalized_answer": _normalize_text(row.get("actual_answer")),
        "expected_answer": _normalize_text(row.get("expected_answer")),
        "expected_points": _normalize_list(row.get("expected_points")),
        "judge_model": _normalize_text(chat_model),
        # Judge scoring sees citations. Keep the cache conservative when evidence changes.
        "citation_signature": _citation_signature(row.get("actual_citations")),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest(), payload


def _load_cache(cache_path: str | Path | None = None) -> dict:
    path = Path(cache_path) if cache_path else default_judge_cache_path()
    if not path.is_file():
        return {"schema_version": JUDGE_CACHE_SCHEMA_VERSION, "entries": {}}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": JUDGE_CACHE_SCHEMA_VERSION, "entries": {}}
    if not isinstance(parsed, dict):
        return {"schema_version": JUDGE_CACHE_SCHEMA_VERSION, "entries": {}}
    entries = parsed.get("entries")
    if not isinstance(entries, dict):
        entries = {}
    return {"schema_version": JUDGE_CACHE_SCHEMA_VERSION, "entries": entries}


def _save_cache(cache: dict, cache_path: str | Path | None = None) -> None:
    path = Path(cache_path) if cache_path else default_judge_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _json_safe(value: dict) -> dict:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _normalize_text(value) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _normalize_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_normalize_text(item) for item in value]


def _citation_signature(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    fields = ("id", "chunk_key", "document_id", "file_title", "section_title")
    signature = []
    for citation in value:
        if not isinstance(citation, dict):
            continue
        item = {
            field: _normalize_text(citation.get(field))
            for field in fields
            if citation.get(field) is not None
        }
        signature.append(item)
    return signature
