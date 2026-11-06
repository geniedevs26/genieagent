# Troubleshooting

Start with these two commands; they print safe JSON and never reveal secrets:

```bash
python scripts/pipeline_report.py          # writes data/dashboard.json
python scripts/pipeline_sync.py --direction pull
```

## Provider errors

### Apollo

| Symptom | Cause / fix |
| --- | --- |
| `apollo: company search failed with HTTP 401` | wrong or missing `APOLLO_API_KEY`; create a key in Apollo → Settings → API Keys |
| `HTTP 403` / `API_INACCESSIBLE` | the plan or API key lacks access to that endpoint; `mixed_companies/search` needs an API-enabled plan |
| `HTTP 422` on search | invalid filter value, e.g. an unsupported employee range; use `11,50` style buckets |
| `HTTP 429` | rate limit; lower `APOLLO_PAGES`/`APOLLO_PER_PAGE`, increase `GENIE_REQUEST_PAUSE` |
| Discovery returns companies but no emails | expected: Apollo people search never returns emails; Hunter handles email |

### Hunter

| Symptom | Cause / fix |
| --- | --- |
| `HTTP 401` | `HUNTER_API_KEY` missing/invalid |
| `HTTP 402` / quota message | out of searches or verifications; check the Hunter dashboard and wait for the monthly reset |
| `email_status=accept_all` for every lead | the domain accepts any address; these are stored but never marked verified or contacted |
| `email_status=not_found` | no public business email on the domain; leave it and let a human decide |
| Verifier returns `202` | Hunter is still checking; the client records `unknown` and does not retry blindly |

### Gemini

| Symptom | Cause / fix |
| --- | --- |
| `Configuration error: GEMINI_MODEL=gemini-1.5-flash is retired` | use `gemini-3.8-flash` (or `gemini-3.5-flash-lite`) |
| `gemini: generateContent failed with HTTP 404` | model id wrong for your API version; keep `GEMINI_BASE_URL` default and a current model |
| `HTTP 429` / `RESOURCE_EXHAUSTED` | free-tier rate limit; lower per-run limits, wait |
| `prompt blocked` | safety filter; review the evidence text, do not try to bypass it |
| `response was not valid JSON` | transient; the stage marks the lead `needs_review` and retries next run |
| Leads marked `needs_review` with "No source-linked business requirement" | correct behaviour: Apollo-only companies have no stated need. Import buyer evidence first (`pipeline_import.py`) |

### Google Sheets

| Symptom | Cause / fix |
| --- | --- |
| `Google Sheets is not configured` | `GOOGLE_SHEETS_ID` plus one auth mode is required |
| `HTTP 403 PERMISSION_DENIED` | spreadsheet not shared with the service-account email, or wrong account for the OAuth token |
| `HTTP 401` after a week | OAuth app in **Testing** expires refresh tokens after 7 days; publish the app to production or use a service account |
| `invalid_grant` | refresh token revoked/expired; re-run the OAuth Playground flow |
| `google-auth` import error | only needed for service accounts; `pip install google-auth` or switch to OAuth refresh tokens |
| `HTTP 429` / quota | writes are chunked; wait a minute and re-run the sync |
| `Timed out waiting for lock` | another pipeline run is active; wait for it to finish |
| Headers duplicated | do not rename tab headers manually to different names; extra columns are preserved, renamed mandatory columns are appended |

### Brevo SMTP

| Symptom | Cause / fix |
| --- | --- |
| `Brevo SMTP authentication failed` | use the SMTP login and SMTP key from Brevo → SMTP & API → SMTP, not the account password |
| `SMTP refused the recipient` | invalid/blocked address; lead is marked failed, review manually |
| `SMTP send outcome is ambiguous` | network failure mid-send; do NOT auto-retry. Check the Brevo log, then approve a new draft if needed |
| Sender rejected | `BREVO_SENDER_EMAIL` must be a verified sender/domain in Brevo |
| Delivery status stays `smtp_accepted` | SMTP acceptance is not delivery; set `BREVO_API_KEY` and run `pipeline_track.py --brevo` for delivered/bounce events |

### WhatsApp

| Symptom | Cause / fix |
| --- | --- |
| `WhatsApp provider is not configured` | `WHATSAPP_PROVIDER=none`; set `meta_cloud` or `green_api` plus credentials |
| `Meta Cloud API requires an approved message template` | expected for first contact; create/approve a template and set `WHATSAPP_TEMPLATE_NAME` |
| `Invalid OAuth access token` | temporary Meta token expired (24h); generate a system-user token |
| `131026` / message undeliverable | recipient has no WhatsApp or blocked the sender |
| Green API `HTTP 401` | wrong `GREEN_API_ID_INSTANCE`/`GREEN_API_TOKEN` |
| Green API instance not authorised | scan the QR in the Green API console; keep the phone online |
| Draft skipped: "No documented consent basis" | set `consent_basis` and `phone_type=business` on the lead before a WhatsApp draft is allowed |

## Pipeline behaviour

* `status: skipped` with a reason = configuration missing, not a crash.
* `stage_send` returning `skipped` when you expected a send = `OUTREACH_SEND_ENABLED`
  is false, or `--execute`/`--unattended` flags were not passed.
* Drafts not created: lead is not `qualified`, email is not Hunter-`valid`, a
  draft is already pending, or draft validation rejected placeholders/portfolio.
* Follow-up not created: not enough days elapsed (default 5/12/21), a reply or
  bounce was recorded, a follow-up is already pending, or all follow-ups are used.
* `data/dashboard.json` not changing: run `python scripts/pipeline_report.py`.

## Termux

| Symptom | Fix |
| --- | --- |
| `python: command not found` | `pkg install python`, or use `python3` |
| `No module named genieagent` | run scripts from the repository root; scripts add the repo to `sys.path` |
| `Permission denied` writing `data/` | avoid read-only shared storage; keep the repo in `$HOME` |
| Android kills the process | use `tmux` or rely on GitHub Actions |
| `pkg install` fails | `pkg update && pkg upgrade -y`, then `termux-change-repo` |
| Slow/large output | add `--limit 5` and check the JSON summary |

## Git and privacy

* Never `git add .env`, `data/leads.csv`, `data/outreach.csv` or logs with contact
  details. They are in `.gitignore`; do not force-add them.
* If a key was ever committed, rotate it at the provider immediately — removing
  the commit is not enough.
* The published dashboard only contains masked contacts; if you see a full email
  on the site, stop the Pages deployment and inspect `data/dashboard.json`.

## Tests

```bash
python -m unittest discover -s tests -t . -v
```

The suite is offline: it uses fake Apollo/Hunter/Gemini/SMTP/WhatsApp transports
and an in-memory Sheets API, so a failure is a real regression, not a credential
problem.
