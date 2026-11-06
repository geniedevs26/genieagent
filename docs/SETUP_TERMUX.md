# Termux setup (Android)

Everything in this repository runs on the Python standard library, so no native
wheel has to be compiled on the phone. Optional `google-auth` is only needed if
you choose service-account auth for Google Sheets.

## 1. Install packages

```bash
pkg update && pkg upgrade -y
pkg install -y python git
python --version        # 3.11+ expected
```

Optional, only if you want n8n orchestration and GitHub cloning helpers:

```bash
pkg install -y nodejs-lts
npm install -g n8n
```

## 2. Get the code

```bash
git clone https://github.com/geniedevs26/genieagent.git ~/genieagent
cd ~/genieagent
git checkout feat/full-architecture-apollo-hunter-gemini-sheets   # until merged to main
```

Termux storage access is not required for the pipeline itself. If you keep the
repo on shared storage, run `termux-setup-storage` first.

## 3. Configure secrets

```bash
cp .env.example .env
nano .env
```

Minimum for the offline-capable stages:

| Variable | Purpose |
| --- | --- |
| `APOLLO_API_KEY` | company discovery |
| `HUNTER_API_KEY` | email discovery/verification |
| `GEMINI_API_KEY` | qualification and drafting |
| `GOOGLE_SHEETS_ID` + OAuth triple | primary database |
| `GENIE_OWNER_EMAIL`, `GENIE_OWNER_NAME`, `GENIE_PORTFOLIO_URL` | draft signature and approval identity |
| `BREVO_SMTP_LOGIN`, `BREVO_SMTP_KEY`, `BREVO_SENDER_EMAIL` | email delivery |

Leave `OUTREACH_SEND_ENABLED=false`, `AUTO_OUTREACH_ENABLED=false` and
`WHATSAPP_SEND_ENABLED=false` until you are ready to contact people.
`chmod 600 .env` and never commit it.

## 4. First run (no sending)

```bash
python scripts/pipeline_import.py --limit 20        # existing research evidence -> leads.csv
python scripts/pipeline_discover.py --limit 10      # Apollo companies (optional)
python scripts/pipeline_enrich.py --limit 10        # Hunter verification
python scripts/pipeline_qualify.py --limit 10       # Gemini scoring
python scripts/pipeline_draft.py --limit 10         # drafts pending approval
python scripts/pipeline_sync.py --direction both    # push/pull Google Sheets
python scripts/pipeline_report.py                   # data/dashboard.json
```

Or run all stages with one command:

```bash
python scripts/run_pipeline.py --limit 10
```

Nothing is sent by these commands. To review drafts:

```bash
python scripts/pipeline_approve.py --list
python scripts/pipeline_approve.py --approve <draft_id> --yes
```

Approval only marks the draft approved. Delivery is a separate, deliberate step:

```bash
OUTREACH_SEND_ENABLED=true python scripts/pipeline_send.py --execute --limit 3
```

Start with `--limit 1` and your own address as a test lead before any real send.

## 5. Keep it running

Termux stops processes when the session ends. Options:

* Run inside `tmux`: `pkg install tmux`, `tmux new -s genie`, then the commands
  above. Detach with `Ctrl-b d`.
* Prefer GitHub Actions for the schedule (nothing to keep alive on the phone):
  see `docs/GITHUB_ACTIONS.md`.
* Use n8n on the phone for scheduling only while Termux stays in the foreground.

Android may still kill background work; do not rely on the phone for guaranteed
delivery timing.

## 6. Backups

`leads.csv`, `outreach.csv` and `activity.csv` live in `data/` and are
gitignored because they contain personal data. Back them up somewhere private:

```bash
mkdir -p ~/storage/shared/genieagent-backup
cp data/*.csv ~/storage/shared/genieagent-backup/
```

The Google Sheet is the primary database; the CSV is the portable backup.

## 7. Updating

```bash
cd ~/genieagent
git pull --ff-only
python -m unittest discover -s tests -t .   # offline regression suite
```

## 8. Troubleshooting

See `docs/TROUBLESHOOTING.md`. Quick checks:

```bash
python -m py_compile genieagent/*.py scripts/pipeline_*.py
python scripts/pipeline_approve.py --list
python scripts/pipeline_sync.py --direction pull
```
