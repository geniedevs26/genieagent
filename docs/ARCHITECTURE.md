# GenieAgent architecture and repository audit

This document records what existed before the change, what was added, and how the
required workflow (A–L) is implemented. It also states plainly what is verified
and what still needs real credentials.

## 1. Audit of the pre-existing repository (branch base: `main`)

The repository already contained a working, Supabase-centric research pipeline
with a Cloudflare Pages owner dashboard. Nothing was deleted or rewritten; the
legacy scripts and workflows are untouched and remain runnable.

| Component | Files | What actually worked | Gaps found |
| --- | --- | --- | --- |
| Public buyer-request research | `scripts/lead_research.py` | Bluesky + Hacker News public APIs, Reddit RSS, strict first-person intent/budget/contact gates, persistent Supabase research cursor, per-page outcomes | Not business-company discovery (no Apollo); no Hunter verification; no AI scoring |
| Remote job research | `scripts/remote_job_research.py`, `.github/workflows/remote-job-research.yml` | Remotive/Arbeitnow/RemoteOK feeds, skill matching, Supabase job sync | Unrelated to the lead pipeline |
| Supabase sync | `scripts/sync_candidates_supabase.py` | Owner-scoped CRM insert/requalify, audit events, dedupe by normalised website | Supabase tables are the storage; no Google Sheets or `leads.csv` |
| Outreach | `scripts/auto_outreach.py` | Personalized templates, portfolio link, daily cap, suppression, uniqueness checks, SMTP acceptance tracking | No Gemini; no Brevo-specific config; no per-message approval for first contact (workflow currently forces `AUTO_OUTREACH_ENABLED: "false"`, README was stale) |
| Reply/order monitoring | `scripts/inbox_monitor.py` | IMAP reply/bounce/opt-out detection, owner-approval creation, bounded AI replies, order stage transitions | IMAP provider, not Brevo events; no WhatsApp |
| Approved stage executor | `scripts/execute_approved_actions.py` | Executes only `status=approved` requests, financial gates, no blind retry | Email only |
| Dashboard | `index.html`, `auto-leads.html`, `functions/api/reddit-feed.js` | Supabase-auth owner desk, approvals, audit views; auto-leads page intentionally shows no candidates | Not readable without Supabase auth; no pipeline/provider view; not a public GitHub Pages status dashboard |
| Security checks | `scripts/check_security.py` | Static assertions on safety gates, secret patterns, CSP, public-feed emptiness | Did not cover Apollo/Hunter/Gemini/Sheets/WhatsApp/n8n |
| CI | `.github/workflows/daily-lead-research.yml`, `static-security-checks.yml` | Hourly research, compile + static checks | No scheduled Sheets/AI pipeline, no manual-only sender, no Pages deploy |
| Docs | `README.md`, `docs/AI_REPLY_SETUP.md` | Supabase/IMAP/Workers AI setup | No Termux, Sheets, n8n, WhatsApp, Apollo/Hunter/Gemini documentation |

Key finding: the README claimed automatic outreach was authorized, while the
scheduled workflow already passed `AUTO_OUTREACH_ENABLED: "false"`. The new
architecture resolves this in favour of the safer, explicit rule required for
this project: **automatic outreach is disabled by default and every message needs
an owner approval.**

## 2. New architecture

```
Apollo (company discovery)
        │
        ├── research_candidates.csv (existing buyer-need evidence, imported)
        ▼
normalise + dedupe (company name / domain / email)
        ▼
Hunter.io (domain search + verifier)  ──► only "valid" becomes contactable
        ▼
Gemini 3.8 Flash (qualification: need + service fit, JSON schema)
        ▼
Gemini 3.8 Flash (personalized email + WhatsApp drafts)
        ▼
leads.csv / outreach.csv  ◄──►  Google Sheets (primary database: Leads, Outreach, Activity)
        ▼
owner approval (Google Sheets column or pipeline_approve.py)
        ▼
Brevo SMTP (email) / Meta Cloud API or Green API (WhatsApp)   ← manual, gated run only
        ▼
tracking (Brevo events, replies, bounces, opt-outs, order status)
        ▼
data/dashboard.json ──► GitHub Pages dashboard (redacted)
```

Orchestration options (same Python code):

* **Termux**: `python scripts/run_pipeline.py --stages ...`
* **n8n**: `n8n/genieagent_pipeline.workflow.json` + manual sender workflow
* **GitHub Actions**: `.github/workflows/genieagent-pipeline.yml` (schedule, never sends) and `genieagent-approved-send.yml` (manual only)

## 3. Required workflow mapping

| Step | Implementation |
| --- | --- |
| A. Discover worldwide business leads | `scripts/pipeline_discover.py` → Apollo `mixed_companies/search` with configurable keywords/locations/employee ranges |
| B. Collect company information with Apollo | Same stage: name, domain, website, country, industry, employee range, Apollo id stored as `source_ref` |
| C. Find/verify emails with Hunter | `scripts/pipeline_enrich.py`: verifies existing public emails; otherwise `domain-search` then `email-verifier` |
| D. Remove duplicates | `genieagent/normalize.py`: normalised company key, domain, email; `dedupe_leads` merges, keeping verified facts |
| E. Qualify on genuine need/fit | `scripts/pipeline_qualify.py`: Gemini JSON-schema result; leads without source-linked evidence are marked `needs_review`, never scored |
| F. Personalized drafts | `scripts/pipeline_draft.py`: Gemini drafts + deterministic validation (length, placeholders, portfolio link) |
| G. Save leads/scores/sources/status in Sheets | `genieagent/storage/sheets.py`; every stage pushes to `Leads`/`Outreach`; full audit in `Activity` |
| H. Export/sync `leads.csv` | `scripts/pipeline_sync.py` (`--direction both/pull/push`); Sheets is authoritative, CSV fills gaps and is the backup |
| I. Email drafts via Brevo SMTP | Drafts carry `provider=brevo_smtp`; sending uses `smtp-relay.brevo.com:587` |
| J. WhatsApp via selected provider | `genieagent/outreach/whatsapp.py` adapters: `meta_cloud`, `green_api`, or `none` |
| K. Track replies/follow-ups/failures/orders | `scripts/pipeline_track.py`, draft/lead statuses, `Activity` tab, Brevo event polling |
| L. Show everything on GitHub Pages | `dashboard.html` + `assets/dashboard.js` reading `data/dashboard.json` |

## 4. Data model

**Leads** (`leads.csv` + `Leads` sheet, key `lead_id`)

Identity: `lead_id`, `company_name`, `normalized_company`, `domain`, `website`,
`country`, `industry`, `employee_range`.
Contact: `contact_name`, `contact_title`, `email`, `email_type`, `email_status`,
`email_score`, `email_verified_at`, `email_source`, `phone_business`,
`phone_source`, `phone_type` (only ever `business`).
Source: `source_provider`, `source_url`, `source_ref`.
Qualification: `service_fit`, `qualification_score`, `qualification_status`,
`qualification_reason`, `need_summary`, `priority`.
Lifecycle: `outreach_status`, `follow_up_count`, `last_contact_at`,
`last_reply_at`, `order_status`, `whatsapp_status`, `do_not_contact`,
`consent_basis`, `notes`, `created_at`, `updated_at`.

**Outreach** (`outreach.csv` + `Outreach` sheet, key `draft_id`)

`lead_id`, `channel` (`email|whatsapp`), `provider`, `recipient`,
`recipient_masked`, `subject`, `body`, `approval_status`, `approved_by`,
`approved_at`, `sent_at`, `provider_message_id`, `delivery_status`,
`failure_reason`, `follow_up_of`, `attempt_count`, timestamps.

**Activity** (local CSV, pushed to the `Activity` sheet)

`event_id`, `timestamp`, `event_type`, `status`, `lead_id`, `summary`, `details`
(JSON, PII-redacted).

Valid status values live in `genieagent/models.py`. `approval_status` is
`draft → pending_owner_approval → approved|rejected|suppressed → sent|failed`.
`delivery_status` distinguishes provider acceptance from confirmed delivery.

## 5. Safety model (enforced in code, not just prose)

| Rule | Enforcement |
| --- | --- |
| Never send without owner approval | `approval_gate()` requires `approval_status=approved`, non-empty `approved_by` equal to `GENIE_OWNER_EMAIL`, and `approved_at` |
| Automatic outreach disabled by default | `Config.outreach_send_enabled` and `auto_outreach_enabled` default `False`; scheduled workflow hard-codes both to `"false"`; `stage_send` returns `skipped` |
| No unattended sending | `pipeline_send.py --unattended` additionally requires `AUTO_OUTREACH_ENABLED=true`; the Actions sender is manual-only |
| Do not contact unverified leads | Email path requires Hunter `valid` **and** `email_verified_at`; `accept_all`/`unknown` are stored but blocked |
| No personal mobile numbers | WhatsApp requires `phone_type=business` and a recorded `consent_basis`; numbers are masked in logs, CSV export for dashboards and UI |
| Never commit credentials | All secrets from env/GitHub Secrets; `.gitignore` excludes `.env` and lead CSVs; `check_security.py` scans for key patterns; Pages build refuses full emails/credentials |
| Respect limits/consent/terms | Configurable pauses, per-run limits, `SUPPRESSED_EMAILS`, opt-out/bounce suppression, Meta template requirement, no retry on sends |
| Do not invent leads or verification | Apollo records have no email; only Hunter outputs are used; qualification refuses leads without source evidence; shadows scores are never generated |

## 6. Idempotency and sync semantics

* Every stage re-reads state, so repeated runs never duplicate a lead, draft or
  event. `lead_id` is deterministic (`stable_id`), draft ids are stable per
  lead/channel/day.
* Sheets writes are read-merge-write with header preservation, so columns added
  by hand are not destroyed; stale trailing rows are cleared.
* Sync direction `both` treats Sheets as authoritative and lets local verified
  facts upgrade empty or weaker fields (`normalize.merge_lead`).
* Delivery facts (`sent_at`, `provider_message_id`, `delivery_status`,
  `failure_reason`) merge newest-wins so an owner editing approval in the sheet
  does not erase a send record.
* Sends are not retried automatically: an ambiguous SMTP/API outcome is recorded
  as failed/unknown for deliberate owner review.

## 7. Honest verification status

Verified locally without credentials:

* 95 offline tests (normalisation/dedupe, CSV store, Sheets table logic with a
  fake API, Gemini JSON parsing/validation, Hunter/Apollo mapping, WhatsApp
  adapter payloads, approval gates, follow-up timing, dashboard redaction,
  full offline pipeline with fake providers and fake SMTP).
* Python compile of all modules/scripts; JSON/YAML validation of n8n and Actions
  definitions; dashboard data generation.

**Not verified** (needs real credentials/accounts, see final report):
Apollo/Hunter/Gemini live calls, Google Sheets live read/write, Brevo SMTP
delivery, Meta/Green API messages, and real GitHub/Actions execution.

## 8. Relationship to the legacy Supabase pipeline

The Supabase CRM, hourly research, inbox monitor and Cloudflare dashboard remain
unchanged. They are a separate, owner-authenticated system. The new pipeline uses
Google Sheets + `leads.csv` as required and shares only the existing research CSV
as an optional evidence source (`pipeline_import.py`). Running both does not
duplicate data across systems: they do not write to each other.
