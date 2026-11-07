# Strict authenticity verification

GenieAgent refuses to treat "a company exists" as "a company wants to buy".
Before a lead can be qualified, drafted or contacted it must pass a deterministic
verification review over the evidence the pipeline already stored.

The review is implemented in [`genieagent/verification.py`](../genieagent/verification.py)
and runs as the `verify` stage (`scripts/pipeline_verify.py`). It never fetches a
web page, never calls an API and never invents a fact. Everything it reports is
derived from a recorded field, and a missing field holds the lead instead of
promoting it.

## Three levels

| Level | Meaning | Can be contacted? |
| --- | --- | --- |
| `verified_genuine` | Identity consistent, requirement source-linked, service matched, business contact verified | Yes, after owner approval and every other send gate |
| `pending_verification` | Something is missing or a review-level flag was found | No |
| `rejected_fraud` | A hard contradiction or high-risk indicator | No, and queued drafts are suppressed |

Only the first level passes `verification_gate()`, which is checked in four
places: `stage_qualify`, `prepare_drafts`, `approval_gate` (every send attempt)
and the dashboard. A draft cannot be created for a held lead even if an operator
edits the sheet by hand, because the gate re-reads the lead at send time.

## What is checked

| Check | Passes when | Holds / rejects when |
| --- | --- | --- |
| Identity | Official website recorded, domain agrees with the website, contact email belongs to that domain | No website, free shared host, bare IP, punycode domain, mismatched domain, free mailbox, unrelated email domain (hold); disposable mailbox or link-shortener website (reject) |
| Fraud screening | No buyer-side demand for money or anonymous contact | Registration/joining/processing fees, upfront payment, security deposit, Western Union, gift cards, crypto, bank details (reject); "Telegram only", "DM me", account-verification language (hold) |
| Requirement | `need_summary`/`notes` contains at least 40 characters of requirement text **and** `source_url` is an http(s) link | Apollo company records, homepage-only data, missing or shortened source link |
| Service match | `service_fit` names a capability the owner actually offers | Empty service fit or an unrelated trade |
| Contact | Business email present, `email_status` is `valid`/`deliverable` and `email_verified_at` is set | Missing email, unverified/`accept_all`/`unknown` status |
| Freshness | `verification_checked_at` is within `GENIE_VERIFICATION_MAX_AGE_DAYS` | Stale verification: the lead is blocked until `pipeline_verify.py` runs again |

Fraud phrases are matched only against buyer-authored text (`need_summary`,
`notes`, `source_ref`, `qualification_reason`), never against the owner's drafts.

### Why a homepage is not evidence

A website proves that a business exists. It does not prove that the business
published a requirement. `requirement_evidence()` therefore requires a distinct
`source_url` and at least 40 characters of requirement text; a homepage URL alone
never qualifies a lead, and Apollo company records are explicitly excluded.

## Recorded audit fields

`Leads` gains eleven columns (created automatically by the Sheets writer):

| Column | Contents |
| --- | --- |
| `verification_status` | `verified_genuine`, `pending_verification` or `rejected_fraud` |
| `verification_reason` | Owner-readable decision with the specific failing facts |
| `identity_status` | `matched`, `unconfirmed` or `mismatch` |
| `verification_method` | `recorded_evidence_review_v1` |
| `verification_sources` | Hostnames and source names only (never an email address) |
| `verification_checks` | JSON array of every check, its result and detail |
| `fraud_indicators` | Pipe-separated screening flags |
| `legal_basis` | The configured outreach basis label (`OUTREACH_LEGAL_BASIS`) |
| `verification_checked_at` | When the review last ran |
| `verified_at` | When the lead last passed (cleared when it stops passing) |
| `verification_fingerprint` | Hash of the verified facts, used to detect changed records |

`verification_fingerprint` covers company, domain, website, email, email status,
source URL, requirement text, service fit and notes. Any change makes
`needs_recheck()` true, so an edited website or email is re-reviewed before it can
be used again.

## Rechecking and revocation

`python scripts/pipeline_verify.py --limit 500` re-assesses recorded leads:

1. Recomputes every check from current data.
2. Rewrites the audit fields and logs `verification_changed` on transitions.
3. For a lead that is no longer `verified_genuine`, sets any queued
   `pending_owner_approval` or `approved` draft to `suppressed` with a
   `Verification: …` reason. Already-sent drafts are left untouched.
4. Pushes the changes to Google Sheets and records `verify_completed` in
   `Activity`.

The scheduled pipeline runs the stage every six hours, and
`genieagent-verification.yml` (daily, plus manual dispatch) provides a
verification-only run. n8n users can import
`n8n/genieagent_verification.workflow.json`.

## Fixing a held lead

A hold is not a permanent judgement; it is a list of missing facts. Correct the
record and re-run verification:

| Reason | Fix |
| --- | --- |
| No official website | Add the business website and domain |
| No source-linked requirement | Add the page where the business states the requirement to `source_url` and a summary to `need_summary` |
| Email status unverified | Run `python scripts/pipeline_enrich.py --limit 10` (Hunter verification) |
| Free mailbox / unrelated domain | Find a company-domain address; the lead stays held otherwise |
| Service fit missing | Record the matched service from the owner's catalogue |
| Verification older than N days | Re-run verification (the review repeats the checks) |

Do not edit `verification_status` by hand to bypass a hold: the next run
recomputes it, and the send gate also re-reads `identity_status`,
`fraud_indicators`, `verified_at` and the contact state.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `GENIE_VERIFICATION_MAX_AGE_DAYS` | `30` | Age after which a verification is stale and blocks outreach |
| `OUTREACH_LEGAL_BASIS` | `legitimate_interest_b2b` | Label recorded on each verified lead; shown on the dashboard. Choosing and defending the actual legal basis remains the owner's responsibility |

## Honest limits

* The checks are deterministic screening, not a legal opinion. A lead that passes
  can still be a bad fit, and a `rejected_fraud` result is a quarantine for
  review, not a criminal finding.
* No live fetch means the pipeline cannot detect a website that changed after the
  lead was recorded until the record itself is updated; the fingerprint detects
  edits to the record, not changes on the internet.
* Domain-history, company-registry, DNS and reputation lookups are not part of
  the current check set. They would need an additional provider with its own free
  limits, and must not be claimed until implemented.
* Email "valid" means the email verifier accepted the address; it does not prove
  the mailbox is read by the person you want.
* The module never sets `do_not_contact = false`, never clears a suppression and
  never changes an approval. Those remain owner actions.

## Tests

`tests/test_verification.py` covers the three levels, each rejection and hold
reason, the audit columns, fingerprint rechecks, stale verification, the send
gate and draft suppression. `tests/test_pipeline_e2e.py` runs the full offline
flow with the verification stage between enrichment and qualification.
