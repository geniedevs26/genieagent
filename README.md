# GenieAgent

Business lead discovery, email verification, AI qualification and **owner-approved**
outreach — built to run on Android/Termux, GitHub Actions and n8n.

* Live legacy owner desk: <https://genieagent.pages.dev/>
* Repository: <https://github.com/geniedevs26/genieagent>
* GitHub Pages dashboard: deploy `dashboard.html` with `.github/workflows/pages.yml` (see below)
* Architecture and audit: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Safety first

* **Automatic outreach is disabled by default.** `OUTREACH_SEND_ENABLED=false`,
  `AUTO_OUTREACH_ENABLED=false`, `WHATSAPP_SEND_ENABLED=false`.
* **Every message needs a per-message owner approval** recorded in the private
  Google Sheet (or with `scripts/pipeline_approve.py`), including approver email
  and timestamp.
* **Unverified contacts are never contacted.** Only Hunter `valid` emails with a
  verification timestamp are eligible; `accept_all` and `unknown` are stored but
  blocked.
* **No personal mobile numbers** are published or messaged; WhatsApp requires a
  business number plus a recorded consent basis.
* **No secrets in git.** Credentials come from environment variables / GitHub
  Secrets; `.env` and lead CSVs are gitignored; static checks scan for key patterns.

## Architecture

```
Apollo ──► normalise/dedupe ──► Hunter (find + verify) ──► Gemini (score + draft)
                                                              │
Google Sheets (primary) ◄──────────── leads.csv / outreach.csv ◄┘
        │                              (local backup + export)
        ▼
owner approval ──► Brevo SMTP (email) / Meta Cloud API or Green API (WhatsApp)
        │
        ▼
tracking (replies, bounces, opt-outs, follow-ups, orders) ──► data/dashboard.json
                                                                   │
                                                            GitHub Pages dashboard
```

| Requirement | Implementation |
| --- | --- |
| Apollo lead/company discovery | `scripts/pipeline_discover.py` |
| Hunter email discovery + verification | `scripts/pipeline_enrich.py` |
| Gemini analysis/qualification/personalization | current model `gemini-3.8-flash`, `scripts/pipeline_qualify.py`, `scripts/pipeline_draft.py` |
| n8n orchestration | `n8n/*.workflow.json`, [docs/N8N_IMPORT.md](docs/N8N_IMPORT.md) |
| Google Sheets primary database | `genieagent/storage/sheets.py`, [docs/GOOGLE_SHEETS_SETUP.md](docs/GOOGLE_SHEETS_SETUP.md) |
| `leads.csv` local/export backup | `scripts/pipeline_sync.py`, `genieagent/storage/csv_store.py` |
| Brevo SMTP delivery | `genieagent/outreach/brevo.py` |
| WhatsApp adapters | `genieagent/outreach/whatsapp.py`, [docs/WHATSAPP.md](docs/WHATSAPP.md) |
| Termux scripts | standard library only, [docs/SETUP_TERMUX.md](docs/SETUP_TERMUX.md) |
| GitHub Actions schedules | [docs/GITHUB_ACTIONS.md](docs/GITHUB_ACTIONS.md) |
| GitHub Pages dashboard | `dashboard.html`, `assets/`, `data/dashboard.json` |

## Quick start (Termux or Linux)

```bash
pkg install -y python git          # Termux
git clone https://github.com/geniedevs26/genieagent.git
cd genieagent
cp .env.example .env               # add your credentials, never commit .env

python scripts/pipeline_import.py --limit 20
python scripts/pipeline_discover.py --limit 10
python scripts/pipeline_enrich.py --limit 10
python scripts/pipeline_qualify.py --limit 10
python scripts/pipeline_draft.py --limit 10
python scripts/pipeline_sync.py --direction both
python scripts/pipeline_report.py
```

Or one command:

```bash
python scripts/run_pipeline.py --limit 10
```

Review and approve drafts:

```bash
python scripts/pipeline_approve.py --list
python scripts/pipeline_approve.py --approve <draft_id> --yes
```

Send deliberately (after setting `OUTREACH_SEND_ENABLED=true`):

```bash
python scripts/pipeline_send.py --execute --limit 1
```

## Required credentials

| Purpose | Variables |
| --- | --- |
| Apollo | `APOLLO_API_KEY` (+ `APOLLO_KEYWORD_TAGS`, `APOLLO_LOCATIONS` to define your ICP) |
| Hunter | `HUNTER_API_KEY` |
| Gemini | `GEMINI_API_KEY`, `GEMINI_MODEL` (default `gemini-3.8-flash`) |
| Google Sheets | `GOOGLE_SHEETS_ID` + (`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REFRESH_TOKEN`) or `GOOGLE_SERVICE_ACCOUNT_JSON` |
| Brevo SMTP | `BREVO_SMTP_LOGIN`, `BREVO_SMTP_KEY`, `BREVO_SENDER_EMAIL` (optional `BREVO_API_KEY` for delivery events) |
| Owner identity | `GENIE_OWNER_EMAIL`, `GENIE_OWNER_NAME`, `GENIE_PORTFOLIO_URL` |
| WhatsApp (optional) | `WHATSAPP_PROVIDER`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_TEMPLATE_NAME` or `GREEN_API_ID_INSTANCE`, `GREEN_API_TOKEN` |

All names and safe defaults are in [.env.example](.env.example). Gemini 1.5
models are retired; the code rejects them with a clear error.

## GitHub Actions

* **GenieAgent pipeline** — every 6 hours: research, verification, qualification,
  drafting, Sheets sync, dashboard snapshot. Sending is hard-disabled.
* **GenieAgent approved outreach** — manual dispatch only, requires the exact
  confirmation text and `OUTREACH_SEND_ENABLED=true`.
* **Deploy GitHub Pages dashboard** — publishes the redacted dashboard.

Enable Pages: Settings → Pages → Source: **GitHub Actions**. Full secrets and
variables tables: [docs/GITHUB_ACTIONS.md](docs/GITHUB_ACTIONS.md).

## Tests

```bash
python -m unittest discover -s tests -t .
python scripts/check_security.py
python -m compileall -q genieagent scripts
```

The 95-test suite is offline (fake providers, fake SMTP, in-memory Sheets), so
passing tests never imply that a live provider call succeeded.

---

## Legacy owner system (unchanged)

The repository also contains the original owner-authenticated Supabase/Cloudflare
pipeline. It still runs independently of the new Google Sheets pipeline:

* `scripts/lead_research.py` — hourly public buyer-request research (Bluesky,
  Hacker News, Reddit RSS) with strict evidence and contact gates.
* `scripts/sync_candidates_supabase.py` — owner-only CRM sync.
* `scripts/inbox_monitor.py` — IMAP reply/bounce/opt-out handling and guarded
  AI replies.
* `scripts/auto_outreach.py` — only drafts by default. The scheduled workflow
  passes `AUTO_OUTREACH_ENABLED: "false"`; outreach requires approval.
* `scripts/execute_approved_actions.py` — proposal/agreement/delivery stages only
  after explicit owner approval.
* `index.html` — Supabase-authenticated owner desk (also served as `/owner.html`
  by the GitHub Pages build).
* `.github/workflows/daily-lead-research.yml`,
  `.github/workflows/remote-job-research.yml`,
  `.github/workflows/static-security-checks.yml`.

Legacy secrets: `SUPABASE_SERVICE_ROLE_KEY`, `GENIE_OWNER_EMAIL`, `SMTP_*`,
`IMAP_*`, optional `CLOUDFLARE_AI_*`. Do not enable automated first-contact
sending in that system either: the required policy for this repository is that
no email or WhatsApp message leaves without an owner approval.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full audit,
[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for fixes, and
[docs/AI_REPLY_SETUP.md](docs/AI_REPLY_SETUP.md) for the optional legacy AI
responder.
