"""CLI entry point for golden-set evaluation."""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from .baseline import attach_baseline_delta, save_accepted_baseline
from .cases import filter_by_slice, filter_quick_cases, load_golden_set
from .common import EVAL_MODES, normalize_eval_mode
from .runner import _get_eval_type, run_eval
from .summary import build_summary, print_summary


def _apply_runtime_overrides(items: list[str]) -> None:
    """Override runtime settings in this eval process only."""
    if not items:
        return
    from app.core.runtime_settings import runtime_settings

    for item in items:
        if "=" not in item:
            raise SystemExit(f"Invalid --runtime-setting {item!r}; expected KEY=VALUE")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise SystemExit(f"Invalid --runtime-setting {item!r}; key is empty")
        runtime_settings._cache[key] = value.strip()


def main():
    parser = argparse.ArgumentParser(description="Golden Set 自动化评估 V2")
    parser.add_argument("--golden-set", required=True, help="JSONL golden set 路径")
    parser.add_argument("--api-base", default="http://127.0.0.1:8010/api",
                        help="API base URL")
    parser.add_argument("--token", default=None, help="API token")
    parser.add_argument("--output", default=None, help="结果 JSONL 路径")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="提交用例的间隔秒数；并发模式下控制提交节流")
    parser.add_argument("--judge", action="store_true", help="启用 LLM judge")
    parser.add_argument("--judge-model", default=None, help="Judge 模型")
    parser.add_argument("--case-timeout", type=int, default=180, help="单题超时秒数")
    parser.add_argument("--concurrency", type=int, default=0,
                        help="并发数；默认 retrieval_only=4，其他模式=2")
    parser.add_argument("--accept-baseline", action="store_true",
                        help="将本次摘要保存为当前 mode/flavor 的 accepted baseline")
    parser.add_argument("--baseline-path", default=None, help="accepted baseline JSON 路径")
    parser.add_argument("--mode", default="full", choices=sorted(EVAL_MODES),
                        help="评测模式: full | quick | retrieval_only | answer_lite")
    parser.add_argument("--slice", action="append", default=[],
                        help="按 tag/flavor/strict 过滤: --slice exact --slice recall --slice strict")
    parser.add_argument("--runtime-setting", action="append", default=[],
                        help="Override local runtime_settings cache for this eval process: KEY=VALUE")
    args = parser.parse_args()
    mode = normalize_eval_mode(args.mode)
    needs_token = mode != "retrieval_only"

    # --- Token ---
    token = args.token
    if needs_token:
        if not token:
            try:
                from app.config import settings
                token = settings.API_TOKEN or ""
            except Exception:
                pass
        if not token:
            env_path = Path(__file__).resolve().parents[2] / ".env"
            if env_path.exists():
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("API_TOKEN="):
                        token = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        if not token:
            print("Error: 需要 --token 或在 .env 中配置 API_TOKEN")
            sys.exit(1)
    token = token or ""

    # --- Load ---
    golden_set = load_golden_set(args.golden_set)
    types = Counter(_get_eval_type(item) for item in golden_set)
    print(f"Loaded {len(golden_set)} questions from {args.golden_set}")
    print(f"  Types: {dict(types)}")
    print(f"  Mode: {mode}")

    # --- Slice filtering ---
    if args.slice:
        golden_set = filter_by_slice(golden_set, args.slice)
        print(f"  Filtered by slice {args.slice}: {len(golden_set)} questions remain")
        if not golden_set:
            print("Error: no questions match the specified slice(s)")
            sys.exit(0)

    if mode == "quick":
        golden_set = filter_quick_cases(golden_set)
        print(f"  Filtered by quick=true: {len(golden_set)} questions remain")
        if not golden_set:
            print("Error: no quick cases found")
            sys.exit(0)

    # --- LLM Judge config (optional, applied per case) ---
    judge_config = None
    if args.judge and mode in {"full", "quick"}:
        judge_model = args.judge_model
        api_key = ""
        base_url = ""
        try:
            from app.config import settings
            if not judge_model:
                judge_model = settings.CHAT_MODEL
            api_key = settings.DEEPSEEK_API_KEY
            base_url = settings.DEEPSEEK_BASE_URL
        except Exception:
            pass
        if not api_key:
            env_path = Path(__file__).resolve().parents[2] / ".env"
            if env_path.exists():
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("DEEPSEEK_API_KEY="):
                        api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    elif line.startswith("DEEPSEEK_BASE_URL="):
                        base_url = line.split("=", 1)[1].strip().strip('"').strip("'")
                    elif line.startswith("CHAT_MODEL=") and not judge_model:
                        judge_model = line.split("=", 1)[1].strip().strip('"').strip("'")

        if not api_key or not judge_model:
            print("Warning: --judge 需要 DEEPSEEK_API_KEY 和 CHAT_MODEL")
        else:
            judge_config = {"chat_model": judge_model, "api_key": api_key, "base_url": base_url}

    # --- Run eval ---
    _apply_runtime_overrides(args.runtime_setting)
    results = run_eval(
        golden_set,
        args.api_base,
        token,
        delay=args.delay,
        case_timeout_sec=args.case_timeout,
        judge_config=judge_config,
        mode=mode,
        concurrency=args.concurrency,
    )

    # --- Save results ---
    output_path = args.output
    if not output_path:
        stem = Path(args.golden_set).stem
        output_path = str(Path(args.golden_set).parent / f"{stem}_results.jsonl")

    with open(output_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nResults saved to {output_path}")

    # --- Save summary ---
    base = Path(output_path).stem
    if base.endswith("_results"):
        base = base[:-len("_results")]
    summary_path = str(Path(output_path).parent / f"{base}_summary.json")

    summary = build_summary(results, mode=mode, output_path=output_path, summary_path=summary_path)
    attach_baseline_delta(summary, baseline_path=args.baseline_path)
    if args.accept_baseline:
        accepted = save_accepted_baseline(summary, baseline_path=args.baseline_path)
        summary.setdefault("baseline", {}).update({
            "available": True,
            "accepted_current_run": True,
            "accepted_at": accepted.get("accepted_at", ""),
            "mode": accepted.get("mode", ""),
            "flavor": accepted.get("flavor", ""),
        })
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"Summary saved to {summary_path}")

    # --- Print terminal summary ---
    print_summary(results, summary=summary)
