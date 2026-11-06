#!/usr/bin/env python3
"""Run several pipeline stages in order (single Termux/n8n command).

Example:
    python scripts/run_pipeline.py --stages import,discover,enrich,qualify,draft,sync,report

``send`` is never included unless explicitly requested. Scheduled runs must use
``--stages ... --no-send`` (the default) so nothing leaves the machine
unattended.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from genieagent.cli import config_from, emit, main_guard, parser_for  # noqa: E402
from genieagent.pipeline import run_stages  # noqa: E402

DEFAULT_STAGES = "import,discover,enrich,qualify,draft,followups,sync,report"


def run() -> int:
    parser = parser_for(description="Run GenieAgent pipeline stages")
    parser.add_argument("--stages", default=DEFAULT_STAGES, help=f"Comma-separated stages (default: {DEFAULT_STAGES}).")
    parser.add_argument("--direction", choices=("both", "pull", "push"), default="both", help="Sheets sync direction.")
    parser.add_argument("--include-whatsapp", action="store_true", help="Prepare WhatsApp drafts when a provider is configured.")
    parser.add_argument("--execute-send", action="store_true", help="Also send approved drafts (requires OUTREACH_SEND_ENABLED=true).")
    parser.add_argument("--unattended", action="store_true", help="Mark the run as unattended (requires AUTO_OUTREACH_ENABLED=true).")
    args = parser.parse_args()
    config = config_from(args)
    stages = [stage.strip() for stage in args.stages.split(",") if stage.strip()]
    if "send" in stages and not args.execute_send:
        return emit(
            {
                "stage": "pipeline",
                "status": "refused",
                "error": "The send stage requires --execute-send. Approved drafts stay queued otherwise.",
            },
            exit_code=2,
        )
    results = run_stages(
        config,
        stages,
        limit=args.limit,
        direction=args.direction,
        include_whatsapp=args.include_whatsapp,
        unattended=args.unattended,
    )
    statuses = {str(result.get("status")) for result in results}
    failed = "failed" in statuses
    emit(
        {"stage": "pipeline", "status": "partial" if failed else "ok", "stages": stages, "results": results},
        title=args.summary_title or "GenieAgent pipeline",
        exit_code=1 if failed else 0,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    main_guard("pipeline", run)
