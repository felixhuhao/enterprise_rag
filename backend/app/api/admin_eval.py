"""Golden set evaluation — POST /admin/eval/run, GET /admin/eval/status."""

import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.api.golden_set_utils import (
    DATA_DIR,
    _backend,
    active_golden_set_path,
    boolish,
    load_jsonl,
    write_jsonl_with_backup,
)
from app.core.auth import CurrentUser
from app.deps import verify_token
from app.rag.query.config import VALID_RETRIEVAL_FLAVORS
from app.services import job_service
from app.utils.schema import ensure_dict

router = APIRouter()

RESULT_DIR = DATA_DIR / "eval_results"
EVAL_MODES = {"full", "quick", "retrieval_only", "answer_lite"}
EVAL_JOB_TYPE = "golden_set_eval"
EVAL_JOB_RESOURCE_TYPE = "eval"
EVAL_JOB_RESOURCE_ID = "golden_set"

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
    "mode": "full",
    "job_id": "",
}


class RunRequest(BaseModel):
    mode: str = "full"
    judge: bool = False
    accept_baseline: bool = False
    case_ids: list[str] = Field(default_factory=list)
    flavor: str = ""
    limit: int = 0
    case_timeout_sec: int = 180
    concurrency: int = 0


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
    return active_golden_set_path()


def _boolish(value) -> bool:
    return boolish(value)


def _case_flavor(case: dict) -> str:
    source_config = ensure_dict(case.get("source_config"))
    return (
        case.get("preferred_flavor")
        or source_config.get("retrieval_flavor")
        or case.get("retrieval_flavor")
        or "balanced"
    )


def _case_strict(case: dict) -> bool:
    source_config = ensure_dict(case.get("source_config"))
    return _boolish(case.get("strict_evidence", source_config.get("strict_evidence", False)))


def _case_enabled(case: dict) -> bool:
    return case.get("status", "active") != "disabled"


def _normalize_eval_mode(value: str | None) -> str:
    mode = (value or "full").strip().lower()
    if mode not in EVAL_MODES:
        raise ValueError(f"评测模式无效: {value}")
    return mode


def _case_quick(case: dict) -> bool:
    return _boolish(case.get("quick", False))


def _filter_cases_for_run(cases: list[dict], req: RunRequest) -> list[dict]:
    mode = _normalize_eval_mode(req.mode)
    selected = [case for case in cases if _case_enabled(case)]
    if req.case_ids:
        allowed = set(req.case_ids)
        selected = [case for case in selected if case.get("id") in allowed]
    if req.flavor:
        selected = [case for case in selected if _case_flavor(case) == req.flavor]
    if mode == "quick":
        selected = [case for case in selected if _case_quick(case)]
    if req.limit and req.limit > 0:
        selected = selected[:req.limit]
    return selected


def _failed_case_count(results: list[dict]) -> int:
    return sum(1 for row in results if _eval_result_preview(row)["status"] == "failed")


def _summarize_golden_case(case: dict) -> dict:
    expected_points = case.get("expected_points", [])
    expected_documents = case.get("expected_documents", [])
    expected_docs = case.get("expected_docs", expected_documents)
    expected_chunk_keys = case.get("expected_chunk_keys", [])
    slices = case.get("slices", case.get("tags", []))
    return {
        "id": case.get("id", ""),
        "question": case.get("question", ""),
        "quick": _case_quick(case),
        "slices": slices if isinstance(slices, list) else [],
        "preferred_flavor": _case_flavor(case),
        "strict_evidence": _case_strict(case),
        "eval_type": case.get("eval_type", ""),
        "level": case.get("level", ""),
        "question_type": case.get("question_type", ""),
        "expected_documents": expected_documents if isinstance(expected_documents, list) else [],
        "expected_docs": expected_docs if isinstance(expected_docs, list) else [],
        "expected_chunk_keys": expected_chunk_keys if isinstance(expected_chunk_keys, list) else [],
        "expected_behavior": case.get("expected_behavior", "answer" if case.get("should_answer", True) else "no_answer"),
        "expected_points": expected_points if isinstance(expected_points, list) else [],
        "expected_answer": case.get("expected_answer", ""),
        "expected_points_count": len(expected_points) if isinstance(expected_points, list) else 0,
        "min_expected_citations": case.get("min_expected_citations"),
        "status": case.get("status", "active"),
        "enabled": _case_enabled(case),
    }


def _load_golden_cases(path: Path) -> list[dict]:
    return load_jsonl(path)


def _write_golden_cases(path: Path, cases: list[dict]) -> None:
    write_jsonl_with_backup(path, cases)


def _normalize_golden_case_update(req: GoldenCaseUpdate) -> dict:
    question = req.question.strip()
    if not question:
        raise ValueError("问题不能为空")
    if req.preferred_flavor not in VALID_RETRIEVAL_FLAVORS:
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
    not_applicable = (
        row.get("verdict") == "not_applicable"
        or (
            row.get("eval_mode") == "retrieval_only"
            and score is None
            and not row.get("hit_metric_applicable")
        )
    )
    if error:
        status = "failed"
        label = "失败"
    elif not_applicable:
        status = "not_applicable"
        label = "不适用"
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
        "failure_category": row.get("failure_category", ""),
        "failure_categories": row.get("failure_categories", []),
        "judge_cache_status": row.get("judge_cache_status", ""),
        "judge_cache_hit": row.get("judge_cache_hit"),
        "judge_cache_usage": row.get("judge_cache_usage", ""),
        "eval_mode": row.get("eval_mode", ""),
        "eval_type": row.get("eval_type", ""),
        "preferred_flavor": row.get("preferred_flavor", ""),
        "actual_retrieval_flavor": row.get("actual_retrieval_flavor"),
        "strict_evidence": row.get("strict_evidence"),
    }


def _eval_result_detail_row(row: dict) -> dict:
    detail = dict(row)
    detail.setdefault("id", "")
    detail.setdefault("question", "")
    detail.setdefault("eval_mode", "")
    detail.setdefault("eval_type", "")
    detail.setdefault("expected_points", [])
    detail.setdefault("expected_docs", detail.get("expected_documents", []))
    detail.setdefault("expected_documents", detail.get("expected_docs", []))
    detail.setdefault("expected_chunk_keys", [])
    detail.setdefault("actual_answer", "")
    detail.setdefault("actual_citations", [])
    detail.setdefault("rerank_results", [])
    detail.setdefault("retrieval_step", {})
    detail.setdefault("trace", {})
    detail.setdefault("failure_categories", [])
    detail.setdefault("failure_category", "")
    detail.setdefault("judge", {})
    detail.setdefault("groundedness", {})
    return detail


def _load_eval_result_row(path: Path, case_id: str) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"评测结果文件不存在: {path}")
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"评测结果文件第 {lineno} 行不是有效 JSON") from exc
        if isinstance(row, dict) and str(row.get("id", "")) == case_id:
            return _eval_result_detail_row(row)
    raise KeyError(case_id)


def _latest_eval_result_paths() -> list[Path]:
    if not RESULT_DIR.is_dir():
        return []
    return sorted(
        RESULT_DIR.glob("*_results.jsonl"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def _find_latest_eval_result_row(case_id: str) -> tuple[Path, dict]:
    last_error: ValueError | None = None
    for path in _latest_eval_result_paths():
        try:
            return path, _load_eval_result_row(path, case_id)
        except KeyError:
            continue
        except ValueError as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise FileNotFoundError("暂无评测结果")


def _current_eval_result_path() -> Path:
    with _lock:
        raw_path = str(_state.get("result_path") or "")
    if not raw_path:
        raise FileNotFoundError("暂无评测结果")
    path = Path(raw_path)
    if not path.is_absolute():
        path = RESULT_DIR / path
    resolved = path.resolve()
    result_dir = RESULT_DIR.resolve()
    try:
        resolved.relative_to(result_dir)
    except ValueError as exc:
        raise ValueError("评测结果路径无效") from exc
    return resolved


def _load_eval_result_row_for_case(case_id: str) -> tuple[Path, dict]:
    try:
        path = _current_eval_result_path()
    except FileNotFoundError:
        return _find_latest_eval_result_row(case_id)

    try:
        return path, _load_eval_result_row(path, case_id)
    except KeyError:
        return _find_latest_eval_result_row(case_id)


def _upsert_result_preview(preview: list[dict], item: dict) -> list[dict]:
    item_id = item.get("id")
    for idx, existing in enumerate(preview):
        if existing.get("id") == item_id:
            return [*preview[:idx], item, *preview[idx + 1:]]
    return [*preview, item]


def _finished_preview_count(preview: list[dict]) -> int:
    return sum(1 for item in preview if item.get("status") != "running")


def _run_job_update(coro):
    try:
        import asyncio
        asyncio.run(coro)
    except Exception:
        # Job updates are observability; they must not break an eval run.
        pass


def _safe_mark_eval_job_running(job_id: str, *, message: str = "running") -> None:
    if not job_id:
        return
    _run_job_update(job_service.mark_job_running(job_id, message=message))


def _safe_update_eval_job_progress(
    job_id: str,
    *,
    progress_current: int | None = None,
    progress_total: int | None = None,
    message: str = "",
) -> None:
    if not job_id:
        return
    _run_job_update(job_service.update_job_progress(
        job_id,
        progress_current=progress_current,
        progress_total=progress_total,
        message=message,
    ))


def _safe_mark_eval_job_succeeded(job_id: str, *, message: str = "") -> None:
    if not job_id:
        return
    _run_job_update(job_service.mark_job_succeeded(job_id, message=message))


def _safe_mark_eval_job_failed(
    job_id: str,
    *,
    error_code: str,
    error_detail: str,
    message: str = "",
) -> None:
    if not job_id:
        return
    _run_job_update(job_service.mark_job_failed(
        job_id,
        error_code=error_code,
        error_detail=error_detail,
        message=message,
    ))


def _update_eval_progress(event: dict, job_id: str = "") -> None:
    job_current = None
    job_total = None
    job_message = ""
    with _lock:
        _state["total"] = event.get("total", _state.get("total", 0))
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
            _state["current"] = _finished_preview_count(_state["results_preview"])
            job_current = _state["current"]
            job_total = _state["total"]
            job_message = f"running {event.get('id', '')}".strip()
        elif event.get("type") == "case_finished":
            row = event.get("row", {})
            _state["current_id"] = row.get("id", "")
            _state["current_question"] = row.get("question", "")
            item = _eval_result_preview(row, event.get("index"), event.get("total"))
            _state["results_preview"] = _upsert_result_preview(_state.get("results_preview", []), item)
            _state["current"] = _finished_preview_count(_state["results_preview"])
            job_current = _state["current"]
            job_total = _state["total"]
            job_message = f"finished {row.get('id', '')}".strip()

    if job_current is not None:
        _safe_update_eval_job_progress(
            job_id,
            progress_current=job_current,
            progress_total=job_total,
            message=job_message,
        )


@router.get("/admin/eval/status")
async def get_eval_status(current_user: CurrentUser = Depends(verify_token)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员")
    with _lock:
        return dict(_state)


@router.get("/admin/eval/result/{case_id}")
async def get_eval_result_case(case_id: str, current_user: CurrentUser = Depends(verify_token)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员")
    try:
        path, row = _load_eval_result_row_for_case(case_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="评测用例结果不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "case_id": case_id,
        "result_path": str(path),
        "preview": _eval_result_preview(row),
        "row": row,
    }


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
    try:
        mode = _normalize_eval_mode(req.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
        _state["mode"] = mode
        _state["job_id"] = ""

    try:
        job = await job_service.create_job(
            job_type=EVAL_JOB_TYPE,
            resource_type=EVAL_JOB_RESOURCE_TYPE,
            resource_id=EVAL_JOB_RESOURCE_ID,
            created_by=current_user.user_id,
            message=f"queued mode={mode}",
        )
    except Exception as exc:
        with _lock:
            _state["status"] = "failed"
            _state["finished_at"] = datetime.now(timezone.utc).isoformat()
            _state["error"] = "评测任务创建失败"
        raise HTTPException(status_code=500, detail="评测任务创建失败，请稍后重试") from exc

    with _lock:
        _state["job_id"] = job["job_id"]

    token = authorization.removeprefix("Bearer ").strip()
    threading.Thread(
        target=_runner, args=(token, req, job["job_id"]), daemon=True,
    ).start()
    return {"ok": True, "status": "running", "job_id": job["job_id"]}


def _runner(token: str, req: RunRequest, job_id: str = ""):
    try:
        _safe_mark_eval_job_running(job_id, message="starting")
        # add backend/ to path so scripts can import app.* modules
        sys.path.insert(0, str(_backend))
        from scripts.eval_golden.cases import load_golden_set
        from scripts.eval_golden.baseline import attach_baseline_delta, save_accepted_baseline
        from scripts.eval_golden.runner import _get_eval_type, run_eval
        from scripts.eval_golden.summary import build_summary

        golden_set_path = _active_golden_set_path()
        mode = _normalize_eval_mode(req.mode)

        golden = _filter_cases_for_run(load_golden_set(str(golden_set_path)), req)
        if not golden:
            raise ValueError("未选择基准测试用例")
        with _lock:
            _state["total"] = len(golden)
        _safe_update_eval_job_progress(
            job_id,
            progress_current=0,
            progress_total=len(golden),
            message=f"running mode={mode}",
        )

        judge_config = None
        if mode in {"full", "quick"} and req.judge and any(_get_eval_type(case) == "llm_judge" for case in golden):
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
            progress_callback=lambda event: _update_eval_progress(event, job_id),
            case_timeout_sec=req.case_timeout_sec,
            judge_config=judge_config,
            mode=mode,
            concurrency=req.concurrency,
        )

        failed_count = _failed_case_count(results)

        # write to disk
        RESULT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        result_path = RESULT_DIR / f"eval_{ts}_results.jsonl"
        summary_path = RESULT_DIR / f"eval_{ts}_summary.json"
        summary = build_summary(
            results,
            mode=mode,
            output_path=str(result_path),
            summary_path=str(summary_path),
        )
        attach_baseline_delta(summary)
        if req.accept_baseline:
            accepted = save_accepted_baseline(summary)
            summary.setdefault("baseline", {}).update({
                "available": True,
                "accepted_current_run": True,
                "accepted_at": accepted.get("accepted_at", ""),
                "mode": accepted.get("mode", ""),
                "flavor": accepted.get("flavor", ""),
            })

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

        final_message = f"results={result_path}; summary={summary_path}"
        _safe_update_eval_job_progress(
            job_id,
            progress_current=len(golden),
            progress_total=len(golden),
            message=final_message,
        )
        if failed_count:
            _safe_mark_eval_job_failed(
                job_id,
                error_code="EVAL_CASES_FAILED",
                error_detail=f"{failed_count} 个用例未通过，基准测试集未通过",
                message=final_message,
            )
        else:
            _safe_mark_eval_job_succeeded(job_id, message=final_message)

    except Exception as exc:
        with _lock:
            _state["status"] = "failed"
            _state["finished_at"] = datetime.now(timezone.utc).isoformat()
            _state["summary"] = None
            _state["error"] = str(exc)[:1000]
        _safe_mark_eval_job_failed(
            job_id,
            error_code="EVAL_ERROR",
            error_detail=str(exc)[:2000],
            message="eval_failed",
        )
