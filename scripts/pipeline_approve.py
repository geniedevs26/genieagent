#!/usr/bin/env python3
"""Owner approval tool for queued drafts.

This is the only command that can mark a draft approved. It requires the owner
email to be configured and records who approved what and when. It never sends:
run ``pipeline_send.py --execute`` afterwards.

Examples:
    python scripts/pipeline_approve.py --list
    python scripts/pipeline_approve.py --approve <draft_id> --yes
    python scripts/pipeline_approve.py --reject <draft_id> --reason "Out of scope" --yes
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from genieagent.cli import config_from, emit, main_guard, parser_for  # noqa: E402
from genieagent.models import APPROVAL_APPROVED, APPROVAL_PENDING, APPROVAL_REJECTED  # noqa: E402
from genieagent.pipeline import log  # noqa: E402
from genieagent.storage.csv_store import outreach_table  # noqa: E402
from genieagent.util import mask_recipient, now_iso  # noqa: E402


def run() -> int:
    parser = parser_for(description="List, approve or reject queued outreach drafts")
    parser.add_argument("--list", action="store_true", help="List drafts awaiting approval.")
    parser.add_argument("--approve", metavar="DRAFT_ID", action="append", default=[])
    parser.add_argument("--reject", metavar="DRAFT_ID", action="append", default=[])
    parser.add_argument("--reason", default="", help="Reason for rejection (recorded).")
    parser.add_argument("--yes", action="store_true", help="Confirm the approval/rejection action.")
    args = parser.parse_args()
    config = config_from(args)
    table = outreach_table(config.outreach_csv)

    if args.list:
        rows = [row for row in table.load() if str(row.get("approval_status")) == APPROVAL_PENDING]
        listing = [
            {
                "draft_id": row.get("draft_id"),
                "channel": row.get("channel"),
                "provider": row.get("provider"),
                "recipient": row.get("recipient_masked") or mask_recipient(str(row.get("channel") or ""), row.get("recipient")),
                "subject": row.get("subject"),
                "company_lead_id": row.get("lead_id"),
                "created_at": row.get("created_at"),
                "body_preview": (row.get("body") or "")[:280],
            }
            for row in rows
        ]
        return emit({"stage": "approve", "status": "ok", "pending": len(listing), "drafts": listing}, title="Drafts awaiting approval")

    if not (args.approve or args.reject):
        parser.error("Use --list, --approve DRAFT_ID or --reject DRAFT_ID.")
    if not args.yes:
        return emit(
            {
                "stage": "approve",
                "status": "confirmation_required",
                "message": "Re-run with --yes to confirm the owner approval decision.",
            },
            exit_code=2,
        )
    if not config.owner_email:
        return emit({"stage": "approve", "status": "failed", "error": "GENIE_OWNER_EMAIL must be set to record approval."}, exit_code=2)

    rows = table.load()
    index = {str(row.get("draft_id")): row for row in rows}
    changed = []
    for draft_id in args.approve:
        row = index.get(draft_id)
        if not row:
            changed.append({"draft_id": draft_id, "status": "not_found"})
            continue
        row["approval_status"] = APPROVAL_APPROVED
        row["approved_by"] = config.owner_email
        row["approved_at"] = now_iso()
        row["updated_at"] = now_iso()
        row["failure_reason"] = ""
        changed.append({"draft_id": draft_id, "status": "approved"})
        log(config, "draft_approved", "ok", "Owner approved one draft", {"draft_id": draft_id, "channel": row.get("channel")}, row.get("lead_id", ""))
    for draft_id in args.reject:
        row = index.get(draft_id)
        if not row:
            changed.append({"draft_id": draft_id, "status": "not_found"})
            continue
        row["approval_status"] = APPROVAL_REJECTED
        row["approved_by"] = config.owner_email
        row["approved_at"] = now_iso()
        row["failure_reason"] = args.reason[:400]
        row["updated_at"] = now_iso()
        changed.append({"draft_id": draft_id, "status": "rejected"})
        log(config, "draft_rejected", "ok", "Owner rejected one draft", {"draft_id": draft_id, "reason": args.reason[:300]}, row.get("lead_id", ""))
    table.upsert(rows)

    if config.sheets_ready:
        from genieagent.storage.sheets import outreach_sheet

        try:
            outreach_sheet(config).upsert([index[item["draft_id"]] for item in changed if item["status"] in {"approved", "rejected"}])
        except Exception as exc:  # pragma: no cover - network dependent
            changed.append({"sheets_sync": "failed", "detail": str(exc)[:200]})

    emit(
        {
            "stage": "approve",
            "status": "ok",
            "changed": changed,
            "next": "Run python scripts/pipeline_send.py --execute to deliver approved messages.",
        },
        title="Owner approval",
    )
    return 0


if __name__ == "__main__":
    main_guard("approve", run)
