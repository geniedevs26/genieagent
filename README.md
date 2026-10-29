# GenieAgent

Owner-only automated client acquisition system: scheduled public research, strict lead qualification, private CRM sync, audit trail, and financial approval gate.

## Live app and source
- Live dashboard: https://genieagent.pages.dev/
- Repository: https://github.com/geniedevs26/genieagent
- Daily workflow: https://github.com/geniedevs26/genieagent/actions/workflows/daily-lead-research.yml

## Automated workflow
1. GitHub Actions runs daily at **01:00 UTC / 06:30 India time**.
2. Public search results are discovery hints only. A record qualifies only if the actual source page contains a requirement phrase and publishes a contact email; search snippets alone are discarded.
3. Only qualified leads sync to the owner's private Supabase CRM. Unverified candidates are not inserted into the CRM.
4. Every confirmed lead automatically receives a **pending financial approval** record. Revenue, tool/API costs, fees, delivery costs, contingency, tax reserve, scope, budget, payment terms and current price evidence must pass the financial gate before a quote or paid commitment.
5. Inserts, updates and deletes for leads, outreach actions, finance entries, workflow runs and financial approvals are captured in `automation_events`. The dashboard displays the latest audit events and financial approval queue.
6. Duplicate website records are skipped. Existing CRM records are not overwritten by research sync.

## One-time setup
In GitHub **Settings → Secrets and variables → Actions → New repository secret**, configure:
- `SUPABASE_SERVICE_ROLE_KEY`: Supabase project server-side service-role/secret key. Keep it secret; never paste it in chat or commit it.
- `GENIE_OWNER_EMAIL`: exact email of the owner account in Supabase Authentication.

Without those two secrets, the workflow safely skips private CRM sync. No recurring manual lead entry is intended; lead research and qualifying records are automated after this one-time setup.

## Financial permission boundary
Financial approvals are deliberately **not automatic**. Confirm the real project scope, client budget/payment, revenue, all costs, net profit, pricing evidence and payment terms before approving. Discovery alone cannot approve spending or a quote. Approval is recorded in the private database and audit history.

## Outbound actions
Automatic client email/calling is **not yet connected**. The current dashboard can prepare/record outreach, but it must not claim that a message was sent or a call completed without a configured provider's confirmation. To make outbound actions automatic, a legitimate sender/provider and its secret must be configured; do not send proposals or commit funds before financial approval.

## Security and records
- Supabase RLS restricts database rows to the authenticated owner.
- Public repository files must not contain lead lists, credentials, API keys or private customer information.
- Export CSV is a backup convenience, not the source of truth; Supabase plus `automation_events` is the persistent record.
- Research is limited by public-page availability and matching evidence; zero results is preferable to inventing confirmed buyer intent.

## Run locally
```bash
python scripts/lead_research.py
```

Cloudflare Pages should use framework preset **None**, no build command, and `/` as the output directory. A new commit deploys when the Pages Git integration is active.
