#!/usr/bin/env python3
"""Stage A/B: discover worldwide business leads and collect Apollo company data.

Usage:
    python scripts/pipeline_discover.py --limit 25

Configuration:
    APOLLO_API_KEY, APOLLO_KEYWORD_TAGS, APOLLO_LOCATIONS,
    APOLLO_EMPLOYEE_RANGES, APOLLO_PAGES, APOLLO_PER_PAGE
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from genieagent.cli import config_from, emit, main_guard, parser_for  # noqa: E402
from genieagent.pipeline import stage_discover  # noqa: E402


def run() -> int:
    parser = parser_for(description="Apollo business lead discovery")
    args = parser.parse_args()
    config = config_from(args)
    result = stage_discover(config, limit=args.limit)
    emit(result, title=args.summary_title or "Apollo discovery")
    return 0


if __name__ == "__main__":
    main_guard("discover", run)
