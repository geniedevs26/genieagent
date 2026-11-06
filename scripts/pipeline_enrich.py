#!/usr/bin/env python3
"""Stage C: find and verify business emails through Hunter.io.

Only Hunter-returned addresses are used. ``valid`` is the only status that
becomes contactable; ``accept_all``/``unknown`` are stored but never marked
verified. A guessed or constructed address is never used.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from genieagent.cli import config_from, emit, main_guard, parser_for  # noqa: E402
from genieagent.pipeline import stage_enrich  # noqa: E402


def run() -> int:
    parser = parser_for(description="Hunter.io business email discovery and verification")
    parser.add_argument("--verify-only", action="store_true", help="Only re-verify emails already on record.")
    args = parser.parse_args()
    config = config_from(args)
    result = stage_enrich(config, limit=args.limit, verify_only=args.verify_only)
    emit(result, title=args.summary_title or "Email enrichment")
    return 0


if __name__ == "__main__":
    main_guard("enrich", run)
