#!/usr/bin/env python3
"""Stage K: track replies, opt-outs, follow-up eligibility, failures and order status.

Examples:
    python scripts/pipeline_track.py --brevo
    python scripts/pipeline_track.py --mark-reply <lead_id> --note "Asked for scope"
    python scripts/pipeline_track.py --mark-optout <lead_id>
    python scripts/pipeline_track.py --order-status <lead_id> proposal_pending

Follow-up drafts are prepared separately by ``pipeline_draft.py --followups``;
they still require owner approval before sending.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from genieagent.cli import config_from, emit, main_guard, parser_for  # noqa: E402
from genieagent.models import ORDER_STATUSES  # noqa: E402
from genieagent.pipeline import mark_opt_out, mark_order_status, mark_reply, stage_track  # noqa: E402
from genieagent.outreach.drafts import plan_follow_up  # noqa: E402
from genieagent.storage.csv_store import leads_table, outreach_table  # noqa: E402


def run() -> int:
    parser = parser_for(description="Track replies, failures, follow-ups and order status")
    parser.add_argument("--brevo", action="store_true", help="Poll Brevo delivery events (needs BREVO_API_KEY).")
    parser.add_argument("--mark-reply", metavar="LEAD_ID", default="")
    parser.add_argument("--mark-optout", metavar="LEAD_ID", default="")
    parser.add_argument("--order-status", nargs=2, metavar=("LEAD_ID", "STATUS"), default=None)
    parser.add_argument("--note", default="")
    parser.add_argument("--followup-report", action="store_true", help="Report which leads have a follow-up due.")
    args = parser.parse_args()
    config = config_from(args)
    results = []

    if args.mark_reply:
        results.append(mark_reply(config, args.mark_reply, args.note))
    if args.mark_optout:
        results.append(mark_opt_out(config, args.mark_optout, args.note))
    if args.order_status:
        lead_id, status = args.order_status
        if status not in ORDER_STATUSES:
            return emit(
                {"stage": "track", "status": "invalid", "error": f"STATUS must be one of {', '.join(ORDER_STATUSES)}"},
                exit_code=2,
            )
        results.append(mark_order_status(config, lead_id, status, args.note))
    if args.brevo:
        results.append(stage_track(config))
    if args.followup_report:
        leads = leads_table(config.leads_csv).load()
        drafts = outreach_table(config.outreach_csv).load()
        due = []
        for lead in leads:
            lead_drafts = [row for row in drafts if row.get("lead_id") == lead.get("lead_id")]
            needs, previous, reason = plan_follow_up(lead, lead_drafts, config)
            if needs:
                due.append(
                    {
                        "lead_id": lead.get("lead_id"),
                        "company": lead.get("company_name"),
                        "previous_draft_id": previous,
                        "reason": reason,
                    }
                )
        results.append({"stage": "followup_report", "status": "ok", "due": len(due), "leads": due[:50]})
    if not results:
        parser.error("Choose at least one action (--brevo, --mark-reply, --mark-optout, --order-status, --followup-report).")

    emit({"stage": "track", "status": "ok", "actions": results}, title=args.summary_title or "Tracking")
    return 0


if __name__ == "__main__":
    main_guard("track", run)
