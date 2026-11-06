#!/usr/bin/env python3
"""Stage F/I/J: prepare personalized email and WhatsApp drafts with Gemini.

Drafts are written to outreach.csv and the Google Sheets ``Outreach`` tab with
``approval_status=pending_owner_approval``. Nothing is sent here.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from genieagent.cli import config_from, emit, main_guard, parser_for  # noqa: E402
from genieagent.pipeline import stage_draft  # noqa: E402


def run() -> int:
    parser = parser_for(description="Prepare AI outreach drafts (owner approval required)")
    parser.add_argument("--followups", action="store_true", help="Prepare due follow-up drafts instead of initial drafts.")
    parser.add_argument("--no-whatsapp", action="store_true", help="Skip WhatsApp drafts even when a provider is configured.")
    args = parser.parse_args()
    config = config_from(args)
    result = stage_draft(
        config,
        limit=args.limit,
        include_whatsapp=not args.no_whatsapp,
        followups=args.followups,
    )
    emit(result, title=args.summary_title or "Outreach drafts")
    return 0


if __name__ == "__main__":
    main_guard("draft", run)
