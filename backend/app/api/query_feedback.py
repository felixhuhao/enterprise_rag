"""Answer feedback — POST /query/feedback, GET /query/feedback (admin)."""

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.golden_set_utils import (
    DATA_DIR,
    active_golden_set_path,
    append_jsonl_with_backup,
    boolish,
    load_jsonl,
)
from app.core.auth import CurrentUser
from app.core.database import get_db
from app.deps import verify_token
from app.rag.query.metadata_utils import parse_json_list

router = APIRouter()

GOLDEN_DRAFT_DIR = DATA_DIR / "golden_set_drafts"
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


class GoldenDraftUpdate(BaseModel):
    question: str = Field(..., max_length=4000)
    preferred_flavor: str = "balanced"
    strict_evidence: bool = False
    eval_type: str = "llm_judge"
    expected_answer: str = ""
    expected_points: list[str] = []
    expected_documents: list[str] = []
    min_expected_citations: int = 1
    notes: str = ""


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

    draft_ids = _draft_feedback_ids()
    records = []
    for row in rows:
        item = dict(row)
        item["in_golden_draft"] = item.get("id") in draft_ids
        records.append(item)
    return records


@router.get("/query/feedback/golden-drafts")
async def list_golden_drafts(
    current_user: CurrentUser = Depends(verify_token),
):
    """List feedback-origin golden-set drafts (admin only)."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可查看基准测试集草稿")
    return {
        "path": str(GOLDEN_DRAFT_PATH),
        "drafts": _load_golden_drafts(),
    }


@router.put("/query/feedback/golden-drafts/{draft_id}")
async def update_golden_draft(
    draft_id: str,
    body: GoldenDraftUpdate,
    current_user: CurrentUser = Depends(verify_token),
):
    """Update one feedback-origin golden-set draft (admin only)."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可编辑基准测试集草稿")
    drafts = _load_golden_drafts()
    for idx, draft in enumerate(drafts):
        if draft.get("id") == draft_id:
            updated = _update_draft_fields(draft, body)
            drafts[idx] = updated
            _save_golden_drafts(drafts)
            return {"ok": True, "draft": updated, "path": str(GOLDEN_DRAFT_PATH)}
    raise HTTPException(status_code=404, detail="基准测试集草稿不存在")


@router.delete("/query/feedback/golden-drafts/{draft_id}")
async def delete_golden_draft(
    draft_id: str,
    current_user: CurrentUser = Depends(verify_token),
):
    """Delete one feedback-origin golden-set draft (admin only)."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可删除基准测试集草稿")
    drafts = _load_golden_drafts()
    next_drafts = [draft for draft in drafts if draft.get("id") != draft_id]
    if len(next_drafts) == len(drafts):
        raise HTTPException(status_code=404, detail="基准测试集草稿不存在")
    _save_golden_drafts(next_drafts)
    return {"ok": True, "path": str(GOLDEN_DRAFT_PATH)}


@router.post("/query/feedback/golden-drafts/{draft_id}/publish")
async def publish_golden_draft(
    draft_id: str,
    current_user: CurrentUser = Depends(verify_token),
):
    """Publish one complete draft into the active Golden Set JSONL file."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可发布基准测试集草稿")
    from app.api.admin_eval import is_eval_running

    if is_eval_running():
        raise HTTPException(status_code=409, detail="评测正在运行，不能修改基准测试集")

    drafts = _load_golden_drafts()
    draft = next((item for item in drafts if item.get("id") == draft_id), None)
    if not draft:
        raise HTTPException(status_code=404, detail="基准测试集草稿不存在")
    _validate_publishable_draft(draft)

    path = _active_golden_set_path()
    cases = _load_jsonl(path)
    if any(case.get("id") == draft["id"] for case in cases):
        raise HTTPException(status_code=409, detail="基准测试集中已存在相同 ID")
    if any(case.get("question", "").strip() == draft.get("question", "").strip() for case in cases):
        raise HTTPException(status_code=409, detail="基准测试集中已存在相同问题")

    case = _draft_to_golden_case(draft)
    _append_jsonl_with_backup(path, case)
    _save_golden_drafts([item for item in drafts if item.get("id") != draft_id])
    return {"ok": True, "case": case, "path": str(path), "draft_path": str(GOLDEN_DRAFT_PATH)}


@router.post("/query/feedback/{feedback_id}/golden-draft")
async def promote_feedback_to_golden_draft(
    feedback_id: int,
    current_user: CurrentUser = Depends(verify_token),
):
    """Add one feedback record to a golden-set draft JSONL file (admin only)."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可加入基准测试集草稿")

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
    for item in _load_golden_drafts():
        if item.get("source_feedback_id") == feedback_id:
            return item
    return None


def _load_golden_drafts() -> list[dict]:
    return load_jsonl(GOLDEN_DRAFT_PATH, skip_invalid=True)


def _save_golden_drafts(drafts: list[dict]) -> None:
    GOLDEN_DRAFT_DIR.mkdir(parents=True, exist_ok=True)
    with open(GOLDEN_DRAFT_PATH, "w", encoding="utf-8") as f:
        for draft in drafts:
            f.write(json.dumps(draft, ensure_ascii=False) + "\n")


def _update_draft_fields(draft: dict, body: GoldenDraftUpdate) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    points = [item.strip() for item in body.expected_points if item and item.strip()]
    docs = [item.strip() for item in body.expected_documents if item and item.strip()]
    flavor = _normalize_flavor(body.preferred_flavor)
    updated = {
        **draft,
        "question": body.question.strip(),
        "eval_type": body.eval_type if body.eval_type in {"llm_judge", "rule", "no_answer"} else "llm_judge",
        "preferred_flavor": flavor,
        "strict_evidence": bool(body.strict_evidence),
        "expected_answer": body.expected_answer.strip(),
        "expected_points": points,
        "expected_documents": docs,
        "min_expected_citations": max(1, int(body.min_expected_citations)),
        "source_config": {
            "retrieval_flavor": flavor,
            "strict_evidence": bool(body.strict_evidence),
        },
        "notes": body.notes.strip(),
        "updated_at": now,
    }
    return updated


def _validate_publishable_draft(draft: dict) -> None:
    if not str(draft.get("question", "")).strip():
        raise HTTPException(status_code=400, detail="草稿缺少问题")
    points = draft.get("expected_points", [])
    if not isinstance(points, list) or not [p for p in points if str(p).strip()]:
        raise HTTPException(status_code=400, detail="发布前至少填写一个验收点")


def _draft_to_golden_case(draft: dict) -> dict:
    flavor = _normalize_flavor(draft.get("preferred_flavor", "balanced"))
    strict = _boolish(draft.get("strict_evidence", False))
    return {
        **draft,
        "preferred_flavor": flavor,
        "strict_evidence": strict,
        "source_config": {
            "retrieval_flavor": flavor,
            "strict_evidence": strict,
        },
        "status": "active",
        "published_at": datetime.now(timezone.utc).isoformat(),
    }


def _active_golden_set_path() -> Path:
    return active_golden_set_path(create=True)


def _load_jsonl(path: Path) -> list[dict]:
    return load_jsonl(path)


def _append_jsonl_with_backup(path: Path, item: dict) -> None:
    append_jsonl_with_backup(path, item)


def _draft_feedback_ids() -> set[int]:
    ids: set[int] = set()
    for item in _load_golden_drafts():
        feedback_id = item.get("source_feedback_id")
        if isinstance(feedback_id, int):
            ids.add(feedback_id)
        elif isinstance(feedback_id, str) and feedback_id.isdigit():
            ids.add(int(feedback_id))
    return ids


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
        "bad_citations": parse_json_list(record.get("citations", "[]")),
        "retrieved_chunks": parse_json_list(record.get("retrieved_chunks", "[]")),
        "source_config": {
            "retrieval_flavor": retrieval_flavor,
            "strict_evidence": strict_evidence,
        },
        "user_id": record.get("user_id", ""),
        "status": "draft",
        "created_at": created_at,
        "notes": "发布到正式基准测试集前，请补充 expected_answer 和 expected_points。",
    }


def _normalize_flavor(value: str) -> str:
    return value if value in {"balanced", "exact", "recall", "discovery"} else "balanced"


def _boolish(value) -> bool:
    return boolish(value)
