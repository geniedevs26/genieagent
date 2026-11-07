# n8n import instructions

Definitions live in [`n8n/`](../n8n):

* `genieagent_pipeline.workflow.json` — 6-hour schedule: research, verification,
  qualification, drafting, Sheets sync and dashboard report. Never sends.
* `genieagent_verification.workflow.json` — daily recheck of recorded leads:
  recomputes the three verification levels, suppresses invalid queued drafts and
  refreshes the dashboard. Never sends.
* `genieagent_approved_outreach.workflow.json` — manual trigger only: pulls sheet
  approvals, sends approved drafts, records results.

Full prerequisites and notes: [`n8n/README.md`](../n8n/README.md).

## Import steps

1. Start n8n (`n8n start` in Termux, or your n8n instance).
2. **Workflows → ⋯ (top right) → Import from File**.
3. Select the JSON file and save.
4. Open **Run pipeline (no sending)** and confirm the command path matches your
   clone (`cd "$HOME/genieagent"` by default).
5. Run it once with **Execute Workflow** and confirm `exitCode` is `0`.
6. Activate the scheduled workflow.
7. Import the verification-recheck workflow and activate it if you want the
   daily authenticity recheck (the 6-hour pipeline already runs the stage).
8. Import the approved-outreach workflow but keep it **inactive** — it is
   manual-only by design.

## How the manual sender works

1. Open the workflow, click **Execute Workflow**.
2. In the **Confirmation** node, set `confirm` to `SEND APPROVED DRAFTS`
   (and optionally lower `limit`).
3. The IF node refuses to continue on any other value.
4. The scripts re-check every gate: strict verification level and freshness,
   approval status, approver identity, verified email, score threshold,
   opt-out/bounce, suppression and duplicates.

## Requirements

* `n8n-nodes-base.executeCommand` (built in) and a shell that can run Python.
* A `.env` in the repository directory with the provider credentials.
* Keep WhatsApp and email send flags `false` unless you intend to contact people.

## Troubleshooting

* `command not found: python` → use `python3` in the node command.
* `exitCode 1` with `Configuration error` → a required env var is missing in `.env`.
* n8n truncates long output; read the step output or run the same command in
  Termux to see the full JSON.
