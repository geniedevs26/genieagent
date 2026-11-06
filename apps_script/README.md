# GenieAgent approval sidebar (Google Apps Script)

A container-bound Apps Script that adds a **GenieAgent → Review pending drafts**
menu to the GenieAgent CRM spreadsheet. From the sidebar you can read each queued
message, then approve or reject it. The approval is written to the `Outreach` tab
exactly as `scripts/pipeline_approve.py` would write it:

| Column | Approve | Reject |
| --- | --- | --- |
| `approval_status` | `approved` | `rejected` |
| `approved_by` | your configured owner email | your configured owner email |
| `approved_at` | UTC timestamp | UTC timestamp |
| `updated_at` | UTC timestamp | UTC timestamp |
| `failure_reason` | cleared | your reason (max 400 chars) |

Each decision also appends one line to the `Activity` tab
(`draft_approved` / `draft_rejected`, `source: apps_script_sidebar`). No other
column is touched, so lead data, sent timestamps and delivery facts survive.

## What it deliberately does not do

* **It cannot send.** There is no `MailApp`, `GmailApp` or `UrlFetchApp` call in
  the project, and the manifest requests no mail or external-request scope.
  Delivery still happens only through `scripts/pipeline_send.py --execute`, which
  re-checks every gate: `OUTREACH_SEND_ENABLED`, a matching owner email, a
  verification timestamp, qualification, suppression and duplicate-send checks.
* It does not verify emails, call Apollo/Hunter/Gemini, or edit lead rows.
* It does not approve on a schedule or in bulk: one card, one decision.

## Install (about three minutes)

1. Open the GenieAgent CRM spreadsheet.
2. **Extensions → Apps Script**. Rename the project to `GenieAgent approvals`.
3. Create four files next to the default `Code.gs` (use **+ → Script** and
   **+ → HTML**) and paste the contents of this folder:
   * `Code.gs` (replace the default file)
   * `Logic.gs` (script)
   * `Sidebar.html` (HTML)
   * `Stylesheet.html` (HTML)
   * `JavaScript.html` (HTML)
4. **Project Settings → “Show `appsscript.json` manifest file”**, then replace
   the manifest with [`appsscript.json`](appsscript.json). This is what keeps the
   scope list minimal (`spreadsheets.currentonly`, container UI, email identity).
5. Save, reload the spreadsheet, and accept the authorization prompt on first
   use. If Google shows “unverified app”, choose **Advanced → Go to project**;
   the script is your own copy and requests only the scopes above.
6. Open **GenieAgent → Review pending drafts**. In **Settings**, enter the same
   address you use for `GENIE_OWNER_EMAIL` and save. Approvals are blocked until
   that is set.

The script finds tabs by header, not by position: `Outreach` (needs `draft_id`),
`Leads` (needs `lead_id`) and `Activity` (needs `event_id`). Renamed tabs are
detected automatically; if several candidates exist, create the Script Property
`GENIE_OUTREACH_SHEET` / `GENIE_LEADS_SHEET` / `GENIE_ACTIVITY_SHEET` with the
exact tab name.

If the sidebar reports missing columns, push the canonical header from the
machine that runs the pipeline:

```bash
python scripts/pipeline_sync.py --direction push
```

## Using it

* **Pending** lists each draft with company, channel, masked recipient, subject,
  the full message body and any warnings (unverified email status, unqualified
  lead, follow-up, WhatsApp template requirement).
* **Approve** asks for confirmation, then records your decision. The toast
  repeats that nothing was sent.
* **Reject** optionally records a reason.
* Stale cards are rejected safely: the script re-reads the row under a document
  lock and refuses if the draft is no longer `pending_owner_approval` (for
  example because the CLI or another device already decided it).
* `GenieAgent → Check sheet setup` prints the tabs found, the owner email, the
  signed-in account, pending count and missing columns.

If the signed-in Google account is not the configured owner, approving is
blocked with a clear message. That mirrors the sender, which refuses any draft
whose `approved_by` differs from `GENIE_OWNER_EMAIL`.

## Tests

The decision logic lives in `Logic.gs` and is pure (no SpreadsheetApp), so it is
tested offline:

```bash
node tests/apps_script/logic.test.mjs     # 16 assertions over masking, blockers, decisions
python3 -m unittest tests.test_apps_script # header parity, wiring, no-send, manifest
```

Covered: email/phone masking, pending-only filtering, stale-status rejection,
do-not-contact, unverified email, unqualified lead, owner enforcement, rejection
reason bounds, activity-row alignment and the absence of send APIs. The sidebar
UI itself cannot be executed outside Google Sheets; the local browser check used
a mocked `google.script.run`, so review it once in your own spreadsheet before
relying on it.
