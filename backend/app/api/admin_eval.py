"""Golden set evaluation — POST /admin/eval/run, GET /admin/eval/status."""

import json
import shutil
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import CurrentUser
from app.deps import verify_token

router = APIRouter()

_backend = Path(__file__).resolve().parents[2]
_data_dir = _backend / "data"
if not _data_dir.is_dir():
    _data_dir = _backend.parent / "data"  # local dev fallback
CHALLENGE_GOLDEN_SET_PATH = _data_dir / "challenge_golden_set_v1.jsonl"
LEGACY_GOLDEN_SET_PATH = _data_dir / "enterprise_docs_v1.jsonl"
RESULT_DIR = _data_dir / "eval_results"

_lock = threading.Lock()
_state: dict = {
    "status": "idle",
    "started_at": "",
    "finished_at": "",
    "summary": None,
    "result_path": "",
    "summary_path": "",
    "error": "",
    "total": 0,
    "current": 0,
    "current_id": "",
    "current_question": "",
    "results_preview": [],
}


class RunRequest(BaseModel):
    judge: bool = False
    case_ids: list[str] = Field(default_factory=list)
    flavor: str = ""
    limit: int = 0
    case_timeout_sec: int = 180


class CaseEnabledRequest(BaseModel):
    enabled: bool


class GoldenCaseUpdate(BaseModel):
    question: str
    preferred_flavor: str = "balanced"
    strict_evidence: bool = False
    eval_type: str = "llm_judge"
    expected_answer: str = ""
    expected_points: list[str] = Field(default_factory=list)
    expected_documents: list[str] = Field(default_factory=list)
    min_expected_citations: int = 1


def is_eval_running() -> bool:
    with _lock:
        return _state["status"] == "running"


def _active_golden_set_path() -> Path:
    if CHALLENGE_GOLDEN_SET_PATH.exists():
        return CHALLENGE_GOLDEN_SET_PATH
    if LEGACY_GOLDEN_SET_PATH.exists():
        return LEGACY_GOLDEN_SET_PATH
    raise FileNotFoundError(f"基准测试集不存在: {CHALLENGE_GOLDEN_SET_PATH}")


def _boolish(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _case_flavor(case: dict) -> str:
    source_config = case.get("source_config") if isinstance(case.get("source_config"), dict) else {}
    return (
        case.get("preferred_flavor")
        or source_config.get("retrieval_flavor")
        or case.get("retrieval_flavor")
        or "balanced"
    )


def _case_strict(case: dict) -> bool:
    source_config = case.get("source_config") if isinstance(case.get("source_config"), dict) else {}
    return _boolish(case.get("strict_evidence", source_config.get("strict_evidence", False)))


def _case_enabled(case: dict) -> bool:
    return case.get("status", "active") != "disabled"


def _filter_cases_for_run(cases: list[dict], req: RunRequest) -> list[dict]:
    selected = list(cases)
    if req.case_ids:
        allowed = set(req.case_ids)
        selected = [case for case in selected if case.get("id") in allowed]
    if req.flavor:
        selected = [case for case in selected if _case_flavor(case) == req.flavor]
    if req.limit and req.limit > 0:
        selected = selected[:req.limit]
    return selected


def _failed_case_count(results: list[dict]) -> int:
    return sum(1 for row in results if _eval_result_preview(row)["status"] == "failed")


def _summarize_golden_case(case: dict) -> dict:
    expected_points = case.get("expected_points", [])
    expected_documents = case.get("expected_documents", [])
    return {
        "id": case.get("id", ""),
        "question": case.get("question", ""),
        "preferred_flavor": _case_flavor(case),
        "strict_evidence": _case_strict(case),
        "eval_type": case.get("eval_type", ""),
        "level": case.get("level", ""),
        "question_type": case.get("question_type", ""),
        "expected_documents": expected_documents if isinstance(expected_documents, list) else [],
        "expected_points": expected_points if isinstance(expected_points, list) else [],
        "expected_answer": case.get("expected_answer", ""),
        "expected_points_count": len(expected_points) if isinstance(expected_points, list) else 0,
        "min_expected_citations": case.get("min_expected_citations"),
        "status": case.get("status", "active"),
        "enabled": _case_enabled(case),
    }


def _load_golden_cases(path: Path) -> list[dict]:
    cases: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def _write_golden_cases(path: Path, cases: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_name(f"{path.name}.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        shutil.copy2(path, backup)
    with open(path, "w", encoding="utf-8") as f:
        for case in cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")


def _normalize_golden_case_update(req: GoldenCaseUpdate) -> dict:
    question = req.question.strip()
    if not question:
        raise ValueError("问题不能为空")
    if req.preferred_flavor not in {"balanced", "exact", "recall", "discovery"}:
        raise ValueError("查找策略无效")
    if req.eval_type not in {"llm_judge", "rule", "no_answer"}:
        raise ValueError("评测方式无效")

    expected_points = [p.strip() for p in req.expected_points if p and p.strip()]
    expected_documents = [d.strip() for d in req.expected_documents if d and d.strip()]
    if req.eval_type == "llm_judge" and not expected_points:
        raise ValueError("LLM 评测至少需要 1 个验收点")

    return {
        "question": question,
        "preferred_flavor": req.preferred_flavor,
        "strict_evidence": bool(req.strict_evidence),
        "eval_type": req.eval_type,
        "expected_answer": req.expected_answer.strip(),
        "expected_points": expected_points,
        "expected_documents": expected_documents,
        "min_expected_citations": max(1, int(req.min_expected_citations or 1)),
    }


def _eval_result_preview(row: dict, index: int | None = None, total: int | None = None) -> dict:
    score = row.get("final_score")
    error = row.get("error")
    if error:
        status = "failed"
        label = "失败"
    elif score is None:
        status = "warning"
        label = "待评测"
    elif score >= 0.8:
        status = "passed"
        label = "通过"
    elif score >= 0.5:
        status = "warning"
        label = "警告"
    else:
        status = "failed"
        label = "失败"
    return {
        "id": row.get("id", ""),
        "question": row.get("question", ""),
        "index": index,
        "total": total,
        "status": status,
        "label": label,
        "score": score,
        "error": error or "",
    }


def _upsert_result_preview(preview: list[dict], item: dict) -> list[dict]:
    item_id = item.get("id")
    for idx, existing in enumerate(preview):
        if existing.get("id") == item_id:
            return [*preview[:idx], item, *preview[idx + 1:]]
    return [*preview, item]


def _update_eval_progress(event: dict) -> None:
    with _lock:
        _state["total"] = event.get("total", _state.get("total", 0))
        _state["current"] = event.get("index", _state.get("current", 0))
        if event.get("type") == "case_started":
            _state["current_id"] = event.get("id", "")
            _state["current_question"] = event.get("question", "")
            item = {
                "id": event.get("id", ""),
                "question": event.get("question", ""),
                "index": event.get("index"),
                "total": event.get("total"),
                "status": "running",
                "label": "运行中",
                "score": None,
                "error": "",
            }
            _state["results_preview"] = _upsert_result_preview(_state.get("results_preview", []), item)
        elif event.get("type") == "case_finished":
            row = event.get("row", {})
            _state["current_id"] = row.get("id", "")
            _state["current_question"] = row.get("question", "")
            item = _eval_result_preview(row, event.get("index"), event.get("total"))
            _state["results_preview"] = _upsert_result_preview(_state.get("results_preview", []), item)


@router.get("/admin/eval/status")
async def get_eval_status(current_user: CurrentUser = Depends(verify_token)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员")
    with _lock:
        return dict(_state)


@router.get("/admin/eval/golden-set")
async def get_golden_set(current_user: CurrentUser = Depends(verify_token)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员")
    try:
        path = _active_golden_set_path()
        cases = _load_golden_cases(path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "path": str(path),
        "count": len(cases),
        "enabled_count": sum(1 for case in cases if _case_enabled(case)),
        "cases": [_summarize_golden_case(case) for case in cases],
    }


@router.patch("/admin/eval/golden-set/{case_id}/enabled")
async def set_golden_case_enabled(
    case_id: str,
    req: CaseEnabledRequest,
    current_user: CurrentUser = Depends(verify_token),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员")
    if is_eval_running():
        raise HTTPException(status_code=409, detail="评测正在运行，不能修改基准测试集")
    try:
        path = _active_golden_set_path()
        cases = _load_golden_cases(path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    for case in cases:
        if case.get("id") == case_id:
            case["status"] = "active" if req.enabled else "disabled"
            _write_golden_cases(path, cases)
            return {"ok": True, "path": str(path), "case": _summarize_golden_case(case)}
    raise HTTPException(status_code=404, detail="基准测试用例不存在")


@router.patch("/admin/eval/golden-set/{case_id}")
async def update_golden_case(
    case_id: str,
    req: GoldenCaseUpdate,
    current_user: CurrentUser = Depends(verify_token),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员")
    if is_eval_running():
        raise HTTPException(status_code=409, detail="评测正在运行，不能修改基准测试集")
    try:
        normalized = _normalize_golden_case_update(req)
        path = _active_golden_set_path()
        cases = _load_golden_cases(path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    for case in cases:
        if case.get("id") == case_id:
            case.update(normalized)
            _write_golden_cases(path, cases)
            return {"ok": True, "path": str(path), "case": _summarize_golden_case(case)}
    raise HTTPException(status_code=404, detail="基准测试用例不存在")


@router.post("/admin/eval/run")
async def run_eval(req: RunRequest, current_user: CurrentUser = Depends(verify_token),
                   authorization: str = Header(...)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员")

    with _lock:
        if _state["status"] == "running":
            raise HTTPException(status_code=409, detail="评估正在运行中")
        _state["status"] = "running"
        _state["started_at"] = datetime.now(timezone.utc).isoformat()
        _state["finished_at"] = ""
        _state["summary"] = None
        _state["error"] = ""
        _state["result_path"] = ""
        _state["summary_path"] = ""
        _state["total"] = 0
        _state["current"] = 0
        _state["current_id"] = ""
        _state["current_question"] = ""
        _state["results_preview"] = []

    token = authorization.removeprefix("Bearer ").strip()
    threading.Thread(
        target=_runner, args=(token, req), daemon=True,
    ).start()
    return {"ok": True, "status": "running"}


def _runner(token: str, req: RunRequest):
    try:
        # add backend/ to path so scripts can import app.* modules
        sys.path.insert(0, str(_backend))
        from scripts.eval_golden_set import _get_eval_type, load_golden_set, run_eval, build_summary

        golden_set_path = _active_golden_set_path()

        golden = _filter_cases_for_run(load_golden_set(str(golden_set_path)), req)
        if not golden:
            raise ValueError("未选择基准测试用例")
        with _lock:
            _state["total"] = len(golden)

        judge_config = None
        if req.judge and any(_get_eval_type(case) == "llm_judge" for case in golden):
            from app.config import settings
            if not settings.DEEPSEEK_API_KEY:
                raise RuntimeError("DEEPSEEK_API_KEY not configured, cannot run LLM judge")
            judge_config = {
                "chat_model": settings.CHAT_MODEL,
                "api_key": settings.DEEPSEEK_API_KEY,
                "base_url": settings.DEEPSEEK_BASE_URL,
            }

        api_base = "http://127.0.0.1:8010/api"
        results = run_eval(
            golden,
            api_base,
            token,
            delay=1.0,
            progress_callback=_update_eval_progress,
            case_timeout_sec=req.case_timeout_sec,
            judge_config=judge_config,
        )

        summary = build_summary(results)
        failed_count = _failed_case_count(results)

        # write to disk
        RESULT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        result_path = RESULT_DIR / f"eval_{ts}_results.jsonl"
        summary_path = RESULT_DIR / f"eval_{ts}_summary.json"

        with open(result_path, "w", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        with _lock:
            _state["status"] = "failed" if failed_count else "succeeded"
            _state["finished_at"] = datetime.now(timezone.utc).isoformat()
            _state["summary"] = summary
            _state["result_path"] = str(result_path)
            _state["summary_path"] = str(summary_path)
            _state["error"] = f"{failed_count} 个用例未通过，基准测试集未通过" if failed_count else ""
            _state["current"] = len(golden)
            _state["total"] = len(golden)

    except Exception as exc:
        with _lock:
            _state["status"] = "failed"
            _state["finished_at"] = datetime.now(timezone.utc).isoformat()
            _state["summary"] = None
            _state["error"] = str(exc)[:1000]
