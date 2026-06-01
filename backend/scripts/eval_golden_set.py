"""Compatibility shim for the split golden-set evaluation package."""

try:
    from scripts.eval_golden import *  # noqa: F401,F403
    from scripts.eval_golden.cli import main
except ModuleNotFoundError:
    from eval_golden import *  # type: ignore # noqa: F401,F403
    from eval_golden.cli import main  # type: ignore


if __name__ == "__main__":
    main()
