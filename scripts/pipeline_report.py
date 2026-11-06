#!/usr/bin/env python3
"""Stage L: export the privacy-safe dashboard payload used by GitHub Pages.

The output (``data/dashboard.json``) never contains full email addresses, phone
numbers, message bodies or credentials. It is safe to commit/publish.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from genieagent.cli import config_from, emit, main_guard, parser_for  # noqa: E402
from genieagent.pipeline import stage_report  # noqa: E402


def run() -> int:
    parser = parser_for(description="Export dashboard data")
    parser.add_argument("--output", default="", help="Output path (defaults to data/dashboard.json).")
    args = parser.parse_args()
    config = config_from(args)
    result = stage_report(config, dashboard_path=Path(args.output) if args.output else None)
    emit(result, title=args.summary_title or "Dashboard export")
    return 0


if __name__ == "__main__":
    main_guard("report", run)
