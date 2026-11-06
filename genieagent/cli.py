"""Shared CLI helpers: config loading, JSON output and GitHub step summaries."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from .config import Config, ConfigError


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--limit", type=int, default=None, help="Maximum records handled in this run.")
    parser.add_argument("--env-file", default=".env", help="Optional dotenv file (never commit it).")
    parser.add_argument("--summary-title", default="", help="Title for the GitHub Actions step summary.")


def parser_for(description: str = "") -> argparse.ArgumentParser:
    """Parser with common flags; callers add their own arguments, then parse."""
    parser = argparse.ArgumentParser(description=description)
    add_common(parser)
    return parser


def config_from(args: argparse.Namespace) -> Config:
    return Config.from_env(dotenv_path=Path(args.env_file) if getattr(args, "env_file", "") else None)


def emit(result: Dict[str, Any], title: str = "", exit_code: int = 0) -> int:
    """Print a machine-readable result and append a human summary for Actions."""
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        heading = title or str(result.get("stage") or "GenieAgent")
        try:
            with open(summary_path, "a", encoding="utf-8") as handle:
                handle.write(f"\n## {heading}\n\n```json\n{text}\n```\n")
        except OSError:
            pass
    return exit_code


def fail(stage: str, message: str, exit_code: int = 1) -> int:
    payload = {"stage": stage, "status": "failed", "error": message}
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as handle:
                handle.write(f"\n## {stage} failed\n\n{message}\n")
        except OSError:
            pass
    return exit_code


def main_guard(stage: str, func) -> None:
    """Run a script body with consistent, secret-free error reporting."""
    try:
        code = func()
    except ConfigError as exc:
        code = fail(stage, f"Configuration error: {exc}")
    except KeyboardInterrupt:
        code = fail(stage, "Interrupted by owner.", exit_code=130)
    except Exception as exc:  # noqa: BLE001 - top-level guard, message is redacted by callers
        code = fail(stage, f"{type(exc).__name__}: {str(exc)[:500]}")
    sys.exit(code)
