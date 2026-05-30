"""Answer feedback — POST /query/feedback, GET /query/feedback (admin)."""

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import CurrentUser
from app.core.database import get_db
from app.deps import verify_token

router = APIRouter()

_backend = Path(__file__).resolve().parents[2]
_data_dir = _backend / "data"
if not _data_dir.is_dir():
    _data_dir = _backend.parent / "data"
GOLDEN_DRAFT_DIR = _data_dir / "golden_set_drafts"
GOLDEN_DRAFT_PATH = GOLDEN_DRAFT_DIR / "feedback_draft.jsonl"


class FeedbackRequest(BaseModel):
    session_id: str
    message_id: str = ""
    query: str = Field(..., max_length=4000)
    answer: str = ""
    citations: list[dict] = []
    retrieved_chunks: list[dict] = []
    retrieval_flavor: str = "balanced"
    strict_evidence: bool = False
    rating: str  # "up" | "down"
    comment: str = ""


@router.post("/query/feedback")
async def submit_feedback(
    body: FeedbackRequest,
    current_user: CurrentUser = Depends(verify_token),
):
    """提交答案反馈。"""
    if body.rating not in ("up", "down"):
        raise HTTPException(status_code=400, detail="rating must be 'up' or 'down'")

    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO query_feedback "
            "(session_id, message_id, query, answer, citations, retrieved_chunks, "
            "rating, comment, retrieval_flavor, strict_evidence, user_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                body.session_id, body.message_id, body.query, body.answer,
                json.dumps(body.citations, ensure_ascii=False),
                json.dumps(body.retrieved_chunks, ensure_ascii=False),
                body.rating, body.comment[:500],
                _normalize_flavor(body.retrieval_flavor), 1 if body.strict_evidence else 0,
                current_user.user_id, now,
            ),
        )
        await db.commit()
    return {"ok": True}


@router.get("/query/feedback")
async def list_feedback(
    current_user: CurrentUser = Depends(verify_token),
    filter_user_id: str = "",
):
    """返回反馈记录（admin only，可选 filter_user_id）。"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可查看反馈")

    where = "WHERE user_id = ?" if filter_user_id else ""
    params = (filter_user_id,) if filter_user_id else ()
    async with get_db() as db:
        async with db.execute(
            f"SELECT * FROM query_feedback {where} ORDER BY created_at DESC LIMIT 200",
            params,
        ) as cursor:
            rows = await cursor.fetchall()
    return [dict(r) for r in rows]


@router.post("/query/feedback/{feedback_id}/golden-draft")
async def promote_feedback_to_golden_draft(
    feedback_id: int,
    current_user: CurrentUser = Depends(verify_token),
):
    """Add one feedback record to a golden-set draft JSONL file (admin only)."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可加入 Golden Set 草稿")

    async with get_db() as db:
        async with db.execute("SELECT * FROM query_feedback WHERE id = ?", (feedback_id,)) as cursor:
            row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="反馈记录不存在")

    record = dict(row)

    # Backfill chunks and actual query config from online stats when available.
    retrieved_chunks = record.get("retrieved_chunks", "[]")
    async with get_db() as db:
        async with db.execute(
            "SELECT retrieved_chunks, retrieval_flavor, strict_evidence FROM query_run_stats "
            "WHERE session_id = ? AND query = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (record.get("session_id", ""), record.get("query", "")),
        ) as cursor:
            qr = await cursor.fetchone()
        if qr:
            if retrieved_chunks == "[]" or not retrieved_chunks:
                record["retrieved_chunks"] = qr["retrieved_chunks"]
            record["retrieval_flavor"] = qr["retrieval_flavor"]
            record["strict_evidence"] = qr["strict_evidence"]

    existing = _find_existing_draft(feedback_id)
    if existing:
        return {
            "ok": True,
            "status": "exists",
            "draft": existing,
            "path": str(GOLDEN_DRAFT_PATH),
        }

    draft = _build_golden_draft(record)
    GOLDEN_DRAFT_DIR.mkdir(parents=True, exist_ok=True)
    with open(GOLDEN_DRAFT_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(draft, ensure_ascii=False) + "\n")

    return {
        "ok": True,
        "status": "created",
        "draft": draft,
        "path": str(GOLDEN_DRAFT_PATH),
    }


def _find_existing_draft(feedback_id: int) -> dict | None:
    if not GOLDEN_DRAFT_PATH.is_file():
        return None
    with open(GOLDEN_DRAFT_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("source_feedback_id") == feedback_id:
                return item
    return None


def _build_golden_draft(record: dict) -> dict:
    created_at = datetime.now(timezone.utc).isoformat()
    retrieval_flavor = _normalize_flavor(record.get("retrieval_flavor", "balanced"))
    strict_evidence = _boolish(record.get("strict_evidence", False))
    return {
        "id": f"fb_{record['id']}",
        "question": record.get("query", ""),
        "eval_type": "llm_judge",
        "level": "review",
        "question_type": "feedback",
        "preferred_flavor": retrieval_flavor,
        "strict_evidence": strict_evidence,
        "expected_answer": "",
        "expected_points": [],
        "expected_documents": [],
        "min_expected_citations": 1,
        "source": "query_feedback",
        "source_feedback_id": record["id"],
        "feedback_rating": record.get("rating", ""),
        "feedback_comment": record.get("comment", ""),
        "bad_answer": record.get("answer", ""),
        "bad_citations": _json_or_empty_list(record.get("citations", "[]")),
        "retrieved_chunks": _json_or_empty_list(record.get("retrieved_chunks", "[]")),
        "source_config": {
            "retrieval_flavor": retrieval_flavor,
            "strict_evidence": strict_evidence,
        },
        "user_id": record.get("user_id", ""),
        "status": "draft",
        "created_at": created_at,
        "notes": "Fill expected_answer/expected_points before adding this case to the official golden set.",
    }


def _json_or_empty_list(value: str) -> list:
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def _normalize_flavor(value: str) -> str:
    return value if value in {"balanced", "exact", "recall", "discovery"} else "balanced"


def _boolish(value) -> bool:
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)
