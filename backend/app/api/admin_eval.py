"""Golden set evaluation — POST /admin/eval/run, GET /admin/eval/status."""

import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app.core.auth import CurrentUser
from app.deps import verify_token

router = APIRouter()

_backend = Path(__file__).resolve().parents[2]
_data_dir = _backend / "data"
if not _data_dir.is_dir():
    _data_dir = _backend.parent / "data"  # local dev fallback
GOLDEN_SET_PATH = _data_dir / "enterprise_docs_v1.jsonl"
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
}


class RunRequest(BaseModel):
    judge: bool = False


@router.get("/admin/eval/status")
async def get_eval_status(current_user: CurrentUser = Depends(verify_token)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员")
    with _lock:
        return dict(_state)


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

    token = authorization.removeprefix("Bearer ").strip()
    threading.Thread(
        target=_runner, args=(token, req.judge), daemon=True,
    ).start()
    return {"ok": True, "status": "running"}


def _runner(token: str, judge: bool):
    try:
        # add backend/ to path so scripts can import app.* modules
        sys.path.insert(0, str(_backend))
        from scripts.eval_golden_set import load_golden_set, run_eval, run_judge, build_summary

        if not GOLDEN_SET_PATH.exists():
            raise FileNotFoundError(f"Golden set not found: {GOLDEN_SET_PATH}")

        golden = load_golden_set(str(GOLDEN_SET_PATH))
        if not golden:
            raise ValueError("Golden set is empty")

        api_base = "http://127.0.0.1:8010/api"
        results = run_eval(golden, api_base, token, delay=1.0)

        if judge:
            from app.config import settings
            from scripts.eval_golden_set import _verdict
            if not settings.DEEPSEEK_API_KEY:
                raise RuntimeError("DEEPSEEK_API_KEY not configured, cannot run LLM judge")
            run_judge(
                results,
                chat_model=settings.CHAT_MODEL,
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_BASE_URL,
            )
            for r in results:
                if (r.get("eval_type") == "llm_judge"
                        and "judge" in r
                        and "error" not in r.get("judge", {})):
                    j = r["judge"]
                    js = j.get("score", 0)
                    cs = r.get("citation_score", 0)
                    r["judge_score"] = js
                    r["final_score"] = round(0.75 * js + 0.25 * cs, 4)
                    r["verdict"] = j.get("verdict", _verdict(r["final_score"]))

        summary = build_summary(results)

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
            _state["status"] = "succeeded"
            _state["finished_at"] = datetime.now(timezone.utc).isoformat()
            _state["summary"] = summary
            _state["result_path"] = str(result_path)
            _state["summary_path"] = str(summary_path)
            _state["error"] = ""

    except Exception as exc:
        with _lock:
            _state["status"] = "failed"
            _state["finished_at"] = datetime.now(timezone.utc).isoformat()
            _state["summary"] = None
            _state["error"] = str(exc)[:1000]
