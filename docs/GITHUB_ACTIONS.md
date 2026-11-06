# GitHub Actions configuration

Three workflows were added. Existing workflows (`daily-lead-research.yml`,
`remote-job-research.yml`, `static-security-checks.yml`) are unchanged.

| Workflow | Trigger | Can it send? |
| --- | --- | --- |
| `genieagent-pipeline.yml` | every 6 hours (`41 */6 * * *`) + manual | **No.** `OUTREACH_SEND_ENABLED`, `AUTO_OUTREACH_ENABLED` and `WHATSAPP_SEND_ENABLED` are hard-coded to `"false"` in the job env. |
| `genieagent-approved-send.yml` | **manual only** (`workflow_dispatch`) | Yes, only for drafts already marked approved, and only when the confirmation text matches. |
| `pages.yml` | push to `main` touching dashboard files + manual | No. Builds and deploys the static dashboard. |

## 1. Secrets (repository → Settings → Secrets and variables → Actions → Secrets)

| Secret | Required for |
| --- | --- |
| `APOLLO_API_KEY` | company discovery |
| `HUNTER_API_KEY` | email discovery + verification |
| `GEMINI_API_KEY` | qualification, drafting |
| `GOOGLE_SHEETS_ID` | primary database |
| `GOOGLE_OAUTH_CLIENT_ID` | Sheets auth (OAuth mode) |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Sheets auth (OAuth mode) |
| `GOOGLE_OAUTH_REFRESH_TOKEN` | Sheets auth (OAuth mode) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Sheets auth (service-account mode, alternative) |
| `GENIE_OWNER_EMAIL` | approval identity and Reply-To |
| `SUPPRESSED_EMAILS` | optional never-contact list |
| `BREVO_SMTP_LOGIN` | email delivery (send workflow only) |
| `BREVO_SMTP_KEY` | email delivery |
| `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ACCESS_TOKEN` | optional Meta Cloud API |
| `GREEN_API_ID_INSTANCE`, `GREEN_API_TOKEN` | optional Green API |

## 2. Variables (same page → Variables)

Non-secret configuration so you can see the current value:

| Variable | Example |
| --- | --- |
| `APOLLO_KEYWORD_TAGS` | `web design,digital agency,ecommerce` |
| `APOLLO_LOCATIONS` | `United States,United Kingdom,Australia` (empty = worldwide) |
| `APOLLO_EMPLOYEE_RANGES` | `11,50,51,200` |
| `APOLLO_PAGES`, `APOLLO_PER_PAGE` | `1`, `25` |
| `HUNTER_DOMAIN_LIMIT` | `10` |
| `GEMINI_MODEL` | `gemini-3.8-flash` |
| `GENIE_OWNER_NAME` | `Siva Satya Prasad` |
| `GENIE_PORTFOLIO_URL` | `https://...` |
| `OUTREACH_MIN_SCORE` | `70` |
| `OUTREACH_DAILY_LIMIT` | `10` |
| `BREVO_SMTP_HOST`, `BREVO_SMTP_PORT` | `smtp-relay.brevo.com`, `587` |
| `BREVO_SENDER_EMAIL`, `BREVO_SENDER_NAME` | verified sender |
| `OUTREACH_SEND_ENABLED` | `false` (set `true` only to arm the sender) |
| `WHATSAPP_SEND_ENABLED` | `false` |
| `AUTO_OUTREACH_ENABLED` | `false` (only for deliberate unattended runs) |
| `WHATSAPP_PROVIDER` | `none` / `meta_cloud` / `green_api` |
| `WHATSAPP_TEMPLATE_NAME`, `WHATSAPP_TEMPLATE_LANG` | approved Meta template |

Never put credentials in variables — they are visible in the UI and logs.

## 3. Scheduled research run

`genieagent-pipeline.yml`:

1. checks out the repo,
2. compiles the package and runs the offline test suite,
3. runs `import,discover,enrich,qualify,draft,followups,sync,report`,
4. refuses to proceed if `data/dashboard.json` contains a full email or a phone
   field,
5. uploads the redacted snapshot as an artifact,
6. commits only `data/dashboard.json` back to `main` (when the ref is main) so the
   Pages dashboard refreshes,
7. writes a step summary and an `::error::` annotation on failure.

Failure semantics: provider stages log `skipped` when a credential is missing
(the run still succeeds and the summary says why). Network/provider errors mark
the stage `partial` and appear in the summary; the pipeline does not silently
claim success.

## 4. Sending approved messages

1. In the private Google Sheet `Outreach` tab, review the row and set:
   * `approval_status` = `approved`
   * `approved_by` = the same address as `GENIE_OWNER_EMAIL`
   * `approved_at` = an ISO timestamp (`2026-11-06T10:00:00Z`)
   * optionally edit `subject` / `body`
2. Ensure the repository variable `OUTREACH_SEND_ENABLED=true`.
3. Actions → **GenieAgent approved outreach** → **Run workflow**.
4. Type `SEND APPROVED DRAFTS` in the confirmation field, keep `limit` small
   (1–5) for the first runs.
5. The workflow pulls sheet approvals, sends only eligible drafts, pushes delivery
   records back, refreshes the dashboard and uploads an audit snapshot.

Every gate is re-checked in code:
`approval_gate()` (approver identity, verification, score, opt-out, suppression,
duplicates, consent, provider config, placeholder validation).

## 5. GitHub Pages deployment

1. Repository → **Settings → Pages**.
2. **Build and deployment → Source: GitHub Actions**.
3. Run the **Deploy GitHub Pages dashboard** workflow (or push to `main`).
4. The site is served at `https://<owner>.github.io/genieagent/`, with the
   pipeline dashboard at `/` and the legacy owner desk at `/owner.html`.

The build copies only `dashboard.html`, `assets/`, `data/dashboard.json`,
`index.html`, `auto-leads.html` and `_headers` into `_site`. Lead CSVs are never
published, and the build fails if a full email or credential-like string is found.

Note: this repository also deploys via Cloudflare Pages to
<https://genieagent.pages.dev/>. Both can coexist; GitHub Pages serves the new
pipeline dashboard, Cloudflare keeps serving the existing owner desk.

## 6. Optional: cooldown between runs

The pipeline uses a concurrency group so two runs cannot overlap. If you hit a
provider's rate limit, reduce `APOLLO_PAGES`, `HUNTER_DOMAIN_LIMIT` or the
per-stage limit in the manual dispatch form, or lengthen the cron interval.

## 7. Verify a workflow change locally

```bash
python -m compileall -q genieagent scripts
python -m unittest discover -s tests -t .
python scripts/check_security.py
python - <<'PY'
import glob, json, yaml
for path in glob.glob(".github/workflows/*.yml"):
    yaml.safe_load(open(path, encoding="utf-8"))
for path in glob.glob("n8n/*.json"):
    json.load(open(path, encoding="utf-8"))
print("workflow definitions parse")
PY
```

`act` can run the job locally in Docker, but it cannot validate real credentials.
