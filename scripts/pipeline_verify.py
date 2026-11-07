#!/usr/bin/env python3
"""Strict authenticity verification (three levels) for recorded leads.

Reads only what the pipeline already stored, so the result is reproducible and
no claim is invented. Leads that are not ``verified_genuine`` are never
qualified, drafted or sent, and queued drafts for a revoked lead are suppressed.

Example:
    python scripts/pipeline_verify.py --limit 500
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from genieagent.cli import config_from, emit, main_guard, parser_for  # noqa: E402
from genieagent.pipeline import stage_verify  # noqa: E402


def run() -> int:
    parser = parser_for(description="Verify lead authenticity and screen for fraud")
    args = parser.parse_args()
    config = config_from(args)
    result = stage_verify(config, limit=args.limit)
    emit(result, title=args.summary_title or "Lead verification")
    return 0


if __name__ == "__main__":
    main_guard("verify", run)
