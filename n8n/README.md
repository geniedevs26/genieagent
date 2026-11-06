# n8n workflows (Termux)

Two importable workflows are provided. Both call the Python scripts in this
repository, so n8n is only the scheduler/orchestrator — all safety rules stay in
the Python code that also runs under GitHub Actions and plain Termux.

| File | Trigger | Purpose |
| --- | --- | --- |
| `genieagent_pipeline.workflow.json` | Every 6 hours | Apollo discovery → Hunter verification → Gemini qualification → drafts → Sheets sync → dashboard report. **Never sends.** |
| `genieagent_approved_outreach.workflow.json` | Manual start only | Pulls sheet approvals, sends only `approval_status=approved` drafts, records results, refreshes the report. |

## Prerequisites on the phone

```bash
pkg update && pkg upgrade -y
pkg install -y python git nodejs-lts
git clone https://github.com/geniedevs26/genieagent.git ~/genieagent
cd ~/genieagent
cp .env.example .env
# edit .env: add Apollo/Hunter/Gemini/Sheets credentials, owner email, portfolio URL
python scripts/pipeline_report.py      # smoke test: writes data/dashboard.json
```

Install n8n (Termux):

```bash
npm install -g n8n
n8n --version
```

Start n8n with `n8n start` (Termux cannot keep a background service alive after
the session ends; run it inside `tmux` if you want it to keep working, or rely on
GitHub Actions for the schedule).

## Import

1. Open n8n (`http://localhost:5678` on the phone, or the LAN URL it prints).
2. **Workflows → ⋯ → Import from File**.
3. Choose `n8n/genieagent_pipeline.workflow.json`.
4. Check the **Run pipeline (no sending)** node command path. It assumes
   `$HOME/genieagent`; change it if you cloned elsewhere.
5. Save, then use **Execute Workflow** once to test.
6. Activate the workflow only after the manual test succeeds.
7. Repeat for `genieagent_approved_outreach.workflow.json` (keep it **inactive**;
   it is a manual workflow and should never be scheduled).

## Notes

* The Execute Command node needs the `n8n-nodes-base.executeCommand` node, which
  is built in. No extra community nodes are required.
* n8n does not see your `.env` automatically; the commands `cd` into the repo, so
  `genieagent.config` loads `.env` from there. Never put secrets in n8n node
  parameters — they are stored in the n8n database.
* The send workflow requires `OUTREACH_SEND_ENABLED=true` in `.env`. Keep it
  `false` until you are ready to contact people.
* Every generated draft still needs `approval_status=approved` (with approver and
  timestamp) in the `Outreach` sheet before a send can happen.
* n8n execution logs contain stdout of the scripts. Those outputs are
  privacy-safe (masked recipients, no credentials), which is why the scripts
  avoid printing raw contact details.
