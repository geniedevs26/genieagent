#!/usr/bin/env python3
"""Stage E: qualify leads with Gemini using genuine, source-linked business need.

Never invents evidence: leads without a recorded requirement are marked
``needs_review`` instead of being scored.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from genieagent.cli import config_from, emit, main_guard, parser_for  # noqa: E402
from genieagent.pipeline import stage_qualify  # noqa: E402


def run() -> int:
    parser = parser_for(description="Gemini lead qualification")
    args = parser.parse_args()
    config = config_from(args)
    result = stage_qualify(config, limit=args.limit)
    emit(result, title=args.summary_title or "Lead qualification")
    return 0


if __name__ == "__main__":
    main_guard("qualify", run)
