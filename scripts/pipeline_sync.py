#!/usr/bin/env python3
"""Stage G/H: synchronize Google Sheets (primary database) with leads.csv.

Directions:
    both  (default) Sheets is authoritative; local rows fill gaps and are exported
    pull  Sheets -> leads.csv/outreach.csv
    push  leads.csv/outreach.csv -> Sheets
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from genieagent.cli import config_from, emit, main_guard, parser_for  # noqa: E402
from genieagent.pipeline import stage_sync  # noqa: E402


def run() -> int:
    parser = parser_for(description="Sync Google Sheets and leads.csv")
    parser.add_argument("--direction", choices=("both", "pull", "push"), default="both")
    args = parser.parse_args()
    config = config_from(args)
    result = stage_sync(config, direction=args.direction)
    emit(result, title=args.summary_title or f"Google Sheets sync ({args.direction})")
    return 0


if __name__ == "__main__":
    main_guard("sync", run)
