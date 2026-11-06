#!/usr/bin/env python3
"""Stage D: import existing research candidates (with stated buyer needs) into leads.csv.

Public research rows already contain a source URL and an evidence excerpt. Their
emails are *not* Hunter-verified, so they remain ineligible for outreach until
the enrichment stage verifies them.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from genieagent.cli import config_from, emit, main_guard, parser_for  # noqa: E402
from genieagent.pipeline import stage_import_candidates  # noqa: E402


def run() -> int:
    parser = parser_for(description="Import research candidates into leads.csv")
    parser.add_argument("--source", default="data/research_candidates.csv", help="Research CSV to import.")
    args = parser.parse_args()
    config = config_from(args)
    result = stage_import_candidates(config, source=Path(args.source), limit=args.limit)
    emit(result, title=args.summary_title or "Lead import")
    return 0


if __name__ == "__main__":
    main_guard("import", run)
