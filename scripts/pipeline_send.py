#!/usr/bin/env python3
"""Stage I/J: send only owner-approved drafts through Brevo SMTP / WhatsApp.

Safety gates (all must pass per message):
  * approval_status = approved, with approver + timestamp recorded;
  * OUTREACH_SEND_ENABLED=true (default false);
  * lead qualified, score >= OUTREACH_MIN_SCORE;
  * email verified by Hunter (status valid) or WhatsApp business consent recorded;
  * not opted out, not bounced, not suppressed, no duplicate send.

``--execute`` is required. Without it the script previews what would be sent.
Unattended runs additionally require AUTO_OUTREACH_ENABLED=true.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from genieagent.cli import config_from, emit, main_guard, parser_for  # noqa: E402
from genieagent.pipeline import stage_send  # noqa: E402


def run() -> int:
    parser = parser_for(description="Send owner-approved outreach")
    parser.add_argument("--execute", action="store_true", help="Actually send. Omit for a safe preview.")
    parser.add_argument("--unattended", action="store_true", help="Scheduled run: also requires AUTO_OUTREACH_ENABLED=true.")
    parser.add_argument("--dry-run", action="store_true", help="Prepare and validate without contacting providers.")
    args = parser.parse_args()
    config = config_from(args)
    dry_run = args.dry_run or not args.execute
    result = stage_send(config, limit=args.limit, unattended=args.unattended, dry_run=dry_run)
    if not args.execute:
        result["requested_mode"] = "preview (no --execute)"
    emit(result, title=args.summary_title or "Approved outreach")
    return 0


if __name__ == "__main__":
    main_guard("send", run)
