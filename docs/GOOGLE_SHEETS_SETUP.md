# Google Sheets setup (primary database)

Google Sheets stores the leads, drafts and audit events. `leads.csv` is the local
export/backup. Two authentication routes are supported; both need the
**Google Sheets API** enabled in a Google Cloud project.

## 1. Create the project and spreadsheet

1. <https://console.cloud.google.com/> → create/select a project.
2. **APIs & Services → Library → Google Sheets API → Enable**.
3. Create a spreadsheet, e.g. `GenieAgent CRM`.
4. Copy the id from the URL:
   `https://docs.google.com/spreadsheets/d/`**`THIS_LONG_ID`**`/edit`.
5. Set `GOOGLE_SHEETS_ID=THIS_LONG_ID`.

The scripts create the `Leads`, `Outreach` and `Activity` tabs on first write and
write the header row themselves. You can rename tabs with
`GOOGLE_SHEETS_LEADS_TAB`, `GOOGLE_SHEETS_OUTREACH_TAB`,
`GOOGLE_SHEETS_ACTIVITY_TAB`. Run `python scripts/pipeline_sync.py --direction pull`
first to create them.

## 2. Option A — OAuth refresh token (no extra packages; good for Termux)

1. **APIs & Services → OAuth consent screen**: choose External, fill the app
   name, add your own account under **Test users**.
2. **Credentials → Create credentials → OAuth client ID → Desktop app**.
   Copy the client id and client secret.
3. Open <https://developers.google.com/oauthplayground/>.
4. Click the gear icon → tick **Use your own OAuth credentials** → paste the
   client id and secret.
5. In **Step 1**, enter the scope:
   `https://www.googleapis.com/auth/spreadsheets`
   → **Authorize APIs** → sign in with the account that owns the sheet.
6. **Step 2 → Exchange authorization code for tokens**. Copy the **refresh token**.
7. Set:

```
GOOGLE_OAUTH_CLIENT_ID=...
GOOGLE_OAUTH_CLIENT_SECRET=...
GOOGLE_OAUTH_REFRESH_TOKEN=...
```

Important: while the consent screen stays in **Testing**, Google expires refresh
tokens after 7 days. Either publish the app (**Publish app → In production**; an
unverified app is fine for your own account with a warning) or use Option B.
Never paste these values into chat, issues or the repository.

## 3. Option B — service account (typical for GitHub Actions)

1. **Credentials → Create credentials → Service account**, then open it →
   **Keys → Add key → JSON**. Download the file and keep it private.
2. Enable the Sheets API for the project (step 1).
3. In the spreadsheet, click **Share**, paste the service-account email
   (`...@....iam.gserviceaccount.com`), give it **Editor**.
4. Set one of:
   * `GOOGLE_SERVICE_ACCOUNT_JSON` = the JSON content (GitHub secret), or
   * `GOOGLE_SERVICE_ACCOUNT_JSON` = an absolute path to the JSON file (Termux).
5. Install the optional dependency: `pip install google-auth`.

The scripts detect the mode automatically (`safety_summary()` reports
`google_sheets_auth_mode`).

## 4. Short-lived token (manual one-off only)

`GOOGLE_SHEETS_ACCESS_TOKEN` is accepted for a quick test; it expires in about an
hour and is not suitable for schedules.

## 5. How synchronisation behaves

* Sheets is the **primary** database. `pipeline_sync.py --direction both`:
  1. reads the sheet,
  2. reads local CSV,
  3. merges (`normalize.dedupe_leads` + `merge_lead`): verified emails,
     qualification and lifecycle states win over placeholders,
  4. writes both.
* `--direction pull` copies Sheets → CSV, `--direction push` copies CSV → Sheets.
* Writes preserve columns you add by hand and clear stale trailing rows.
* Approval is read from the `Outreach` tab: edit `approval_status` to `approved`
  and fill `approved_by` (must equal `GENIE_OWNER_EMAIL`) and `approved_at`.
  The scripts never approve anything themselves.
* Local delivery facts (`sent_at`, `provider_message_id`, `delivery_status`,
  `failure_reason`) survive the merge even if the sheet row is older.

## 6. Quotas and reliability

* Sheets API quota is per project and per user; writes are chunked at 500 rows
  and each stage writes once per run.
* If a sync fails, the CSV is still updated locally and the failure is recorded in
  `Activity`; re-run the sync later. Do not run two syncs concurrently — the
  workflows use a concurrency group, and Termux runs take a file lock.
* Sheet formulas or conditional formatting are not modified by the pipeline; only
  cell values are written.

## 7. Verification

```bash
python scripts/pipeline_sync.py --direction pull
python - <<'PY'
from genieagent.config import Config
from genieagent.storage.sheets import leads_sheet
c = Config.from_env()
print(c.sheets_auth_mode, c.sheets_ready)
print(len(leads_sheet(c).load()[1]), "rows visible")
PY
```
